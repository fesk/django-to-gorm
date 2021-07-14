#!/usr/bin/python3
"""
//- Copyright (c) 2021, Nick Besant hwf@fesk.net. All rights reserved.
//- licenced under GPLv3, see LICENCE.txt

django_to_gorm.py - tool to convert a Django models.py file to a starting point for
    a set of golang GORM model definitions.

    Supports common field types (e.g. CharField, IntegerField, BooleanField) and makes
    best-effort attempt to support relationships such as ForeignKey, ManyToManyField, OneToOneField.

    Not recommended for production use.  This is only intended to simplify the lifting work
    required when writing Go code (using GORM) to work with an existing Django app.

    By default, creates a .go file that includes import statements and an example main() func.  Will
    automatically generate User and Group models if they're not present in the models.py file.

    There is minimal error checking / verification (intentionally), this is not meant for
    production use.

    Run as $ python3 django_to_gorm.py to get help.

    View docstring for convert() for extra options if integrating into other things.


"""
import os
import sys
import traceback

TYPE_MAP = {
    'BooleanField': 'bool',
    'IntegerField': 'int',
    'BigIntegerField': 'int64',
    'CharField': 'string',
    'TextField': 'string',
    'DateTimeField': 'time.Time',
    'NullBooleanField': 'sql.NullBool',
    'BinaryField': 'byte[]',
}

DEMO = """
class UserProfile(models.Model):
    user = models.OneToOneField(User, related_name="userprofile", on_delete=models.CASCADE)
    accountsuspended = models.BooleanField('Account suspended', default=False)
    district = models.ForeignKey(District, null=True, related_name='userprofile_company', on_delete=models.SET_NULL)
    lastpasswordchange = models.DateTimeField('Date and time of last password change')
    credits = models.IntegerField('Credit balance', null=True, blank=True)
    homepage = models.IntegerField(default=-1)
    last_login = models.DateTimeField(null=True)
    login_count = models.IntegerField(default=0)
    notes = models.TextField(null=True, default=None)
    language = models.CharField(max_length=20, default='en')
    categories_allowed = models.ManyToManyField(Category)    

    def save(self, *args, **kwargs):
        if self.credits: self.credits = abs(self.credits)
        super(UserProfile, self).save(*args, **kwargs)

    class Meta:
        db_table = 'userprofile'

    def __unicode__(self):
        return '%s - %s' % (self.user, self.company)
"""

IMPORTS = """package main

import
(
	"gorm.io/gorm"
	// Enable one from below as needed, postgres included as default
	"gorm.io/driver/postgres"
	// "gorm.io/driver/mysql"
	// "gorm.io/driver/sqlite"
	"time"
	"fmt"
	"database/sql"
)

"""

TABLE_HELPER = """
type Tabler interface {
	TableName() string
}

"""

USER_MODEL = """
type User struct {
	ID		        int64		`gorm:"primaryKey"`
	Email	        string	    `gorm:"column:email"`
	First_name	    string	    `gorm:"column:first_name"`
	Last_name	    string	    `gorm:"column:last_name"`
	Is_superuser	bool        `gorm:"column:is_superuser"`
	Is_staff	    bool        `gorm:"column:is_staff"`
	Date_joined     time.Time   `gorm:"column:date_joined"`
}

func(User) TableName() string {
	return "auth_user"
}

"""

GROUP_MODEL = """
type Group struct {
	ID		        int64		`gorm:"primaryKey"`
	Name	        string	    `gorm:"column:name"`
}

func(Group) TableName() string {
	return "auth_group"
}

"""

HELPER_REF = """
//
// EXAMPLE / help / reference, update this with your DB type / credentials.
//
func main(){
    dsn := "host=localhost user=USER password=PWD dbname=DBNAME port=5432 TimeZone=Europe/London"
    db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
    if err != nil {
        fmt.Printf("Error connecting: %s\\n", err)
    }
    
    var user User
    db.First(&user)
    fmt.Printf("First email in User table: %s\\n", user.Email)
}"""


def convert(infile=None, outfile=None, include_helpers=True,
            auto_add_user_model=True, auto_add_group_model=True):
    """Write a file containing basic GORM model definitions from a
    Django models.py ORM definitions file.

    :param infile: (str|list) (str) - full path to models.py file (must be
                                        a valid Django models.py file)
                              (list) - list of strings comprising Django models.py
                                        file contents
    :param outfile: (str) full path to output file.  Must not exist.
    :param include_helpers: (bool) - include import statements and a helper/demo func main()
    :param auto_add_user_model: (bool) - if a model like "class User(models.Model)" isn't
                            found, then auto-generate one with Django default fields in it.
    :param auto_add_group_model: (bool) - if a model like "class Group(models.Model)" isn't
                            found, then auto-generate one with Django default fields in it.


    """

    if isinstance(infile, str):
        if not os.path.exists(infile):
            print("\n!! input file {0} not found".format(infile))
            sys.exit()

        with open(infile, 'r') as sourcedata:
            in_lines = sourcedata.readlines()

    else:
        in_lines = infile

    if os.path.exists(outfile):
        print("\n!! output file {0} exists.  Please move/rename it or specify a new output file.".format(outfile))
        sys.exit()

    out_lines = []
    current_model = []
    last_model_closed = False
    got_custom_tables = False
    in_model_def = False
    model_name = ''
    default_table_name = ""
    table_name = ''
    custom_table_name = False
    found_user_table = False
    found_group_table = False

    prev_line = ''
    lines = 1
    errors = []

    def __close_model_def(cm):
        cm.append('}')
        cm.append('')
        if custom_table_name:
            cm.append('func ({0}) TableName() string {{'.format(model_name))
            cm.append('\treturn "{0}"'.format(table_name))
            cm.append('}')
            cm.append('')
            # if custom table name is defined after fields, we won't know about it
            # while writing foreign key names, so rebuild this model definition with
            # the correct table name
            new_current_model = []
            for ol in cm:
                new_current_model.append(ol.replace(default_table_name, table_name))
            out_lines.extend(new_current_model)
        else:
            out_lines.extend(cm)

    for l in in_lines:
        if l.startswith('def ') and in_model_def:
            # Note no spaces/tabs before "def ", which means it's not indented, so
            # not in a current model def.
            in_model_def = False
            __close_model_def(current_model)
            last_model_closed = True
            current_model = []

        # Strip spaces here so that check above works.
        l = l.strip()

        # catch (models.Model), (Model), (MPTTModel) etc.
        if l.startswith('class') and l.endswith('Model):'):
            if in_model_def:
                __close_model_def(current_model)
                last_model_closed = True
                current_model = []

            in_model_def = True
            last_model_closed = False
            model_name = l.split(' ')[1].split('(')[0]
            # Usually missing from models.py, but often referenced by models.
            if model_name == 'User':
                found_user_table = True
            if model_name == 'Group':
                found_group_table = True

            table_name = 'app_{0}s'.format(model_name.lower())
            default_table_name = table_name
            custom_table_name = False
            current_model.append('type {0} struct {{'.format(model_name))

        else:
            if in_model_def:
                if "db_table" in l and '=' in l and not l.startswith('#') and 'class Meta:' in prev_line:
                    # custom db table name
                    custom_table_name = True
                    got_custom_tables = True
                    table_name = l.split('=')[1].strip().replace('u"', '').replace("u'", '').replace('"', '').replace("'", '')
                else:
                    if l.startswith('"""'):
                        current_model.append('\t// {0}'.format(l.replace('"""', '')))

                    elif l.startswith('#'):
                        current_model.append('\t// {0}'.format(l.replace('#', '')))

                    elif '=' in l and 'models.' in l:
                        field_parts = l.split('=')
                        field_name = field_parts[0].strip()

                        try:
                            field_type = field_parts[1].strip().split('.')[1].split('(')[0].strip()
                            if field_name in ['id', 'pk', 'ID', 'PK'] and 'primary_key' in l:
                                current_model.append('\t{0}\t\tint64\t\t`gorm:"primaryKey"`'.format(field_name.upper()))
                            else:
                                gotype = TYPE_MAP.get(field_type, None)

                                if gotype:
                                    current_model.append('\t{0}\t\t{1}\t`gorm:"column:{2}"`'.format(field_name.capitalize(),
                                                                                                gotype,
                                                                                                field_name))
                                else:
                                    try:
                                        fkeymodel = field_parts[1].strip().split('.')[1].split('(')[1].strip().split(',')[0].strip().strip(')')
                                    except:
                                        fkeymodel = '########'
                                    if field_type == 'ForeignKey':
                                        fkey = """`gorm:"foreignKey:{0}_id;association_foreignkey:id"`""".format(field_name)

                                        self_id_field = '\t{0}ID\t\tint64\t{1}'.format(field_name.capitalize(),
                                                                                       fkey)
                                        fkey_field = '\t{0}\t\t{1}'.format(field_name.capitalize(),
                                                                           fkeymodel)
                                        current_model.append(self_id_field)
                                        current_model.append(fkey_field)

                                    elif field_type == 'ManyToManyField':
                                        fkey = """`gorm:"many2many:{0}_{1};joinForeignKey:{0}_id"`""".format(table_name, field_name)
                                        current_model.append('\t\\ !! NOTE: m2m key relationship/name may not work')
                                        current_model.append(
                                            '\t{0}\t\t[]{1}\t{2}'.format(field_name.capitalize(),
                                                                         fkeymodel,
                                                                         fkey))

                                    elif field_type == 'OneToOneField':
                                        fkey = """`gorm:"foreignKey:{0}_id"`""".format(field_name)
                                        self_id_field = '\t{0}ID\t\tint64\t{1}'.format(field_name.capitalize(),
                                                                                       fkey)
                                        fkey_field = '\t{0}\t\t{1}'.format(field_name.capitalize(),
                                                                           fkeymodel)
                                        current_model.append(self_id_field)
                                        current_model.append(fkey_field)

                                    else:
                                        # 'pass' used for reading clarity
                                        if 'getLogger' in l:
                                            pass
                                        elif prev_line.endswith(',') or prev_line.endswith('\\'):
                                            pass
                                        else:
                                            errors.append('{0}: Unknown/unhandled line: {1}'.format(lines, field_type))
                                            current_model.append('\t// !! unknown type in line {0}, original: {1}'.format(lines, l))

                        except:
                            # Don't attempt to handle other models types, e.g. from MPTT models.
                            if 'TreeForeignKey' in l:
                                errors.append('{0}: {1}'.format(lines, l))
                                current_model.append('\t// !! Unhandled item in line {0}, original: {1}'.format(lines, l))
                            else:
                                print("\n\n\n!! Exception (source file #{0})\n\n"
                                      "Source line: {1}\n{2}".format(lines, l, traceback.format_exc()))

                                sys.exit()

        prev_line = l
        lines += 1

    if last_model_closed is False:
        __close_model_def(current_model)

    out_prefix = []

    if include_helpers:
        for p in IMPORTS.split('\n'):
            out_prefix.append(p)

    if got_custom_tables:
        for p in TABLE_HELPER.split('\n'):
            out_prefix.append(p)

    if not found_user_table and auto_add_user_model:
        for p in USER_MODEL.split('\n'):
            out_prefix.append(p)

    if not found_group_table and auto_add_group_model:
        for p in GROUP_MODEL.split('\n'):
            out_prefix.append(p)

    out_lines = out_prefix + out_lines

    with open(outfile, 'w') as out:
        out.write('\n'.join(out_lines))
        if include_helpers:
            out.write(HELPER_REF)

    print("\nOutput file {0} written".format(outfile))

    if errors:
        with open(outfile + '.errors', 'w') as out:
            out.write('\n'.join(errors))
        print("\n!! Errors occurred, {0}.errors log written".format(outfile))


if __name__ == '__main__':

    if len(sys.argv) < 2:
        print("\nBuild a .go file containing GORM model definitions from a Django models.py.")
        print("\npython3 {0} /path/to/models.py [/path/to/gorm_models.go]\n".format(sys.argv[0]))
        print("\n\targ1 is the full path for your Django models.py or DEMO to use built-in demo model")
        print("\targ2 is the full path to write the .go file to (including filename), defaults to ./gorm_models.go\n")
        print("\n\nOr, import this module and call convert(..params...) instead.")
        sys.exit()

    if len(sys.argv) > 2:
        outfile = sys.argv[2]
    else:
        outfile = 'gorm_models.go'

    infile = sys.argv[1]

    if infile == 'DEMO':
        infile = DEMO.split('\n')

    convert(infile, outfile)
