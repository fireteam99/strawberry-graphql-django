from decimal import Decimal
from django.db.models import fields, Model
from typing import List, Optional, cast
from uuid import UUID
import datetime
import strawberry
from . import utils

field_type_map = {
    fields.AutoField: strawberry.ID,
    fields.BigAutoField: strawberry.ID,
    fields.BigIntegerField: int,
    fields.BooleanField: bool,
    fields.CharField: str,
    fields.DateField: datetime.date,
    fields.DateTimeField: datetime.datetime,
    fields.DecimalField: Decimal,
    fields.EmailField: str,
    #TODO: fields.FieldFile
    fields.FilePathField: str,
    fields.FloatField: float,
    #TODO: fields.ImageField
    fields.GenericIPAddressField: str,
    fields.IntegerField: int,
    #TODO: fields.JSONField
    fields.NullBooleanField: Optional[bool],
    fields.PositiveBigIntegerField: int,
    fields.PositiveIntegerField: int,
    fields.PositiveSmallIntegerField: int,
    fields.SlugField: str,
    fields.SmallAutoField: strawberry.ID,
    fields.SmallIntegerField: int,
    fields.TimeField: datetime.time,
    fields.URLField: str,
    fields.UUIDField: UUID,
    fields.TextField: str,
}

def get_field_type(field):
    db_field_type = type(field)
    field_type = field_type_map.get(db_field_type)
    if field_type is None:
        raise TypeError(f'Unknown type for {db_field_type.__name__}')
    return field_type


model_type_map = {
}

def set_model_type(model, field_type):
    model_type_map[model] = field_type

def get_model_type(model):
    model_type = model_type_map.get(model)
    if model_type is None:
        model_type = LazyModelType(model)
    return model_type

class LazyModelType(strawberry.LazyType):
    def __init__(self, model):
        super().__init__('', '', '')
        self.model = model
    def resolve_type(self):
        if self.model not in model_type_map:
            raise Exception(f'GraphQL type not defined for "{self.model._meta.object_name}" Django model.')
        return model_type_map[self.model]


def get_field(field, is_input, is_update):
    field_type = get_field_type(field)

    if is_input and field_type == strawberry.ID:
        return #TODO: is this correct?

    if is_input:
        if field.blank or is_update:
            field_type = Optional[field_type]

    return field.name, field_type, strawberry.arguments.UNSET


def get_relation_field(field):
    if hasattr(field, 'get_accessor_name'):
        field_name = field.get_accessor_name()
    else:
        field_name = field.name
    model = field.related_model
    field_type = get_model_type(model)

    @strawberry.field
    def resolver(info, root, filters: Optional[List[str]] = None) -> List[field_type]:
        #resolver_cls = get_resolver_cls(model)
        #instance = resolver_cls(info, root)
        qs = getattr(root, field_name).all()
        if filters:
            filters, excludes = utils.split_filters(filters)
            if filters:
                qs = qs.filter(**filters)
            if excludes:
                qs = qs.exclude(**excludes)
        return qs


    return field_name, None, resolver


def get_relation_foreignkey_field(field):
    field_name = field.name
    model = field.related_model
    field_type = get_model_type(model)

    @strawberry.field
    def resolver(info, root) -> Optional[field_type]:
        obj = getattr(root, field_name)
        return obj

    return field_name, None, resolver


def generate_model_type(resolver, is_input=False, is_update=False):
    model = resolver.model
    annotations = {}
    attributes = { '__annotations__': annotations }

    # add fields
    for field in model._meta.get_fields():
        if resolver.fields and field.name not in resolver.fields:
            continue # skip
        if resolver.exclude and field.name in resolver.exclude:
            continue # skip
        if field.is_relation:
            if is_input:
                continue
            if isinstance(field, fields.related.ForeignKey):
                field_params = get_relation_foreignkey_field(field)
            else:
                field_params = get_relation_field(field)
        else:
            field_params = get_field(field, is_input, is_update)
        if not field_params:
            continue
        field_name, field_type, field_value = field_params
        attributes[field_name] = field_value
        if field_type:
            annotations[field_name] = field_type
    if not is_input:
        for field_name in dir(resolver):
            field = getattr(resolver, field_name)
            if hasattr(field, '_field_definition'):
                attributes[field_name] = field

    # generate type
    type_name = model._meta.object_name
    if is_update:
        type_name = f'Update{type_name}'
    elif is_input:
        type_name = f'Create{type_name}'
    model_type = type(type_name, (), attributes)
    model_type = strawberry.type(model_type, is_input=is_input)
    if not is_input:
        set_model_type(model, model_type)
    return model_type