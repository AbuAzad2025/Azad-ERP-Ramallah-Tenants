# validators.py - Custom Validators
# Location: /garage_manager/validators.py
# Description: Custom validation functions for forms

from wtforms.validators import ValidationError
from sqlalchemy import func

class Unique:
    def __init__(
        self, model, field, message=None, case_insensitive=False, normalizer=None, pk_name="id"
    ):
        self.model = model              
        self.field = field
        self.message = message or "Value already exists."
        self.case_insensitive = case_insensitive
        self.normalizer = normalizer
        self.pk_name = pk_name

    def __call__(self, form, field):
        data = field.data
        if self.normalizer:
            data = self.normalizer(data)
            if data is not None:
                field.data = data
        if not data:
            return

        if isinstance(self.model, type):
            model = self.model
        elif callable(self.model):
            model = self.model()
        else:
            model = self.model
        query = model.query
        column = getattr(model, self.field)

        if self.case_insensitive and isinstance(data, str):
            query = query.filter(func.lower(column) == data.lower())
        else:
            query = query.filter(column == data)

        if getattr(form, "id", None) and form.id.data:
            query = query.filter(getattr(model, self.pk_name) != form.id.data)

        if query.first():
            raise ValidationError(self.message)


