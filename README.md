# django-to-gorm

Build a file containing GORM model definitions from a Django models.py

This is a **basic** tool to convert a Django models.py file to a starting point for a set of golang GORM model definitions.

Supports common field types (e.g. CharField, IntegerField, BooleanField) and makes best-effort attempt to support relationships such as ForeignKey, ManyToManyField, OneToOneField.

Not recommended for production use.  This is only intended to simplify the lifting work required when writing Go code (using GORM) to work with an existing Django app.

By default, creates a *gorm_models.go* file that includes import statements and an example main() func.  Will automatically generate User and Group models if they're not present in the models.py file.

There is minimal error checking / verification (intentionally), this is not meant for production use.

Errors encountered during processing are written to *outputfilename.go.errors* and where relevant are also included as inline comments in the .go output file within a model definition.

Run;
```$ python3 django_to_gorm.py``` to get help.

View docstring for convert() for extra options if integrating into other things.

Unless your models.py is very basic, **it is highly probable that the output file will contain errors** that will need resolving by hand.  This is most likely to occur with foreign key relationships, because it's not very clever.  Make sure you **check and test** the output file before using it.


