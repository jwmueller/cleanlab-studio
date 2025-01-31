"""
Helper functions for working with schemas
"""
import decimal
import json
import pathlib
import random
import re
from typing import Any, Collection, Dict, List, Optional, Sized, Tuple, IO, Union

import pandas as pd
import requests
import semver
import validators
from pandas import NaT

from cleanlab_studio.cli.classes.dataset import Dataset
from cleanlab_studio.cli.click_helpers import abort, info, progress, success
from cleanlab_studio.cli.dataset.schema_types import (
    DataType,
    FeatureType,
    MEDIA_FEATURE_TYPES,
    Schema,
)
from cleanlab_studio.cli.types import Modality
from cleanlab_studio.cli.util import dump_json
from cleanlab_studio.errors import ColumnMismatchError, EmptyDatasetError
from cleanlab_studio.internal.types import JSONDict
from cleanlab_studio.version import MAX_SCHEMA_VERSION, MIN_SCHEMA_VERSION, SCHEMA_VERSION


def _find_best_matching_column(target_column: str, columns: List[str]) -> Optional[str]:
    """
    Find the column from `columns` that is the closest match to the `target_col`.
    If no columns are likely, pick the first column of `columns`
    If no columns are provided, return None

    :param target_column: some reserved column name, typically: 'id', 'label', or 'text'
    :param columns: non-empty list of column names
    :return:
    """
    if len(columns) == 0:
        return None

    if target_column == "id":
        regex = r"id"
    elif target_column == "filepath":
        regex = r"file|path|dir"
    else:
        regex = r""

    poss = []
    for c in columns:
        if c.lower() == target_column:
            return c
        elif any(re.findall(regex, c, re.IGNORECASE)):
            poss.append(c)

    if len(poss) > 0:  # pick first possibility
        return poss[0]
    else:
        return columns[0]


def load_schema(filepath: str) -> JSONDict:
    with open(filepath, "r") as f:
        schema_dict: JSONDict = json.load(f)
        return schema_dict


def validate_schema(schema: Schema) -> None:
    """
    Checks that:
    (1) all schema column names are strings
    (2) all schema column types are recognized
    Note that schema initialization already checks that all keys are present and that fields are valid.
    :param schema:
    :return: raises a ValueError if any checks fail
    """

    # check schema version validity
    schema_version = schema.version
    if (
        semver.VersionInfo.parse(MIN_SCHEMA_VERSION).compare(schema_version) == 1
    ):  # min schema > schema_version
        raise ValueError(
            "This schema version is incompatible with this version of the CLI. "
            "A new schema should be generated using 'cleanlab dataset schema generate'"
        )
    elif semver.VersionInfo.parse(MAX_SCHEMA_VERSION).compare(schema_version) == -1:
        raise ValueError(
            "CLI is not up to date with your schema version. Run 'pip install --upgrade cleanlab-studio'."
        )

    metadata = schema.metadata

    # Advanced validation checks: this should be aligned with ConfirmSchema's validate() function
    ## Check that specified ID column has the feature_type 'identifier'
    id_column_name = metadata.id_column
    id_column_spec_feature_type = schema.fields[id_column_name].feature_type
    if id_column_spec_feature_type != FeatureType.identifier:
        raise ValueError(
            f"ID column field {id_column_name} must have feature type: 'identifier', but has"
            f" feature type: '{id_column_spec_feature_type}'"
        )

    ## Check that there exists at least one categorical column (to be used as label)
    has_categorical = any(
        spec.feature_type == FeatureType.categorical for spec in schema.fields.values()
    )
    if not has_categorical:
        raise ValueError(
            "Dataset does not seem to contain a label column. (None of the fields is categorical.)"
        )

    ## If tabular modality, check that there are at least two variable (i.e. categorical, numeric, datetime) columns
    modality = metadata.modality
    variable_fields = {FeatureType.categorical, FeatureType.numeric, FeatureType.datetime}
    if modality == Modality.tabular:
        num_variable_columns = sum(
            int(spec.feature_type in variable_fields) for spec in schema.fields.values()
        )
        if num_variable_columns < 2:
            raise ValueError(
                "Dataset modality is tabular; there must be at least one categorical field and one"
                " other variable field (i.e. categorical, numeric, or datetime)."
            )

    ## If text modality, check that at least one column has feature type 'text'
    elif modality == Modality.text:
        has_text = any(spec.feature_type == FeatureType.text for spec in schema.fields.values())
        if not has_text:
            raise ValueError("Dataset modality is text, but none of the fields is a text column.")

    elif modality == Modality.image:
        image_columns = [
            col for col, spec in schema.fields.items() if spec.feature_type == FeatureType.image
        ]
        if not image_columns:
            raise ValueError(
                "Dataset modality is image, but none of the fields is an image column."
            )
        if len(image_columns) > 1:
            raise ValueError("More than one image column in a dataset is not currently supported.")


def multiple_separate_words_detected(values: Collection[Any]) -> bool:
    avg_num_words = sum([len(str(v).split()) for v in values]) / len(values)
    return avg_num_words >= 3


def is_filepath(string: str, check_existing: bool = False) -> bool:
    if pathlib.Path(string).suffix == "" or " " in string:
        return False
    if check_existing:
        return pathlib.Path(string).exists()
    return True


def is_url(string: str, check_existing: bool = False) -> bool:
    if not validators.url(string):
        return False

    try:
        if check_existing:
            requests.head(string)
            return True
    except requests.RequestException:
        return False

    return True


def get_validation_sample_size(values: Sized) -> int:
    return min(20, len(values))


def string_values_are_datetime(values: Collection[Any]) -> bool:
    try:
        # check for datetime first
        val_sample = random.sample(list(values), get_validation_sample_size(values))
        for s in val_sample:
            res = pd.to_datetime(s)
            if res is NaT:
                raise ValueError
    except Exception:
        return False
    return True


def string_values_are_integers(values: Collection[Any]) -> bool:
    try:
        val_sample = random.sample(list(values), get_validation_sample_size(values))
        for s in val_sample:
            if str(int(s)) != s:
                return False
    except Exception:
        return False
    return True


def string_values_are_floats(values: Collection[Any]) -> bool:
    try:
        val_sample = random.sample(list(values), get_validation_sample_size(values))
        for s in val_sample:
            float(s)
    except Exception:
        return False
    return True


def values_are_filepaths(values: Collection[Any]) -> bool:
    val_sample = random.sample(list(values), get_validation_sample_size(values))
    for s in val_sample:
        if not is_filepath(s):
            return False
    return True


def values_are_urls(values: Collection[Any]) -> bool:
    val_sample = random.sample(list(values), get_validation_sample_size(values))
    return all(is_url(s) for s in val_sample)


def infer_types(values: Collection[Any]) -> Tuple[DataType, FeatureType]:
    """
    Infer the data type and feature type of a collection of a values using simple heuristics.

    :param values: a Collection of data values (that are not null and not empty string)
    """
    counts = {DataType.string: 0, DataType.integer: 0, DataType.float: 0, DataType.boolean: 0}
    ID_RATIO_THRESHOLD = 0.97  # lowerbound
    CATEGORICAL_RATIO_THRESHOLD = 0.20  # upperbound

    ratio_unique = len(set(values)) / len(values)
    for v in values:
        if v == "":
            continue
        if isinstance(v, str):
            counts[DataType.string] += 1
        elif isinstance(v, float):
            counts[DataType.float] += 1
        elif isinstance(v, bool):  # must come before int: isinstance(True, int) evaluates to True
            counts[DataType.boolean] += 1
        elif isinstance(v, int):
            counts[DataType.integer] += 1
        elif isinstance(v, decimal.Decimal):  # loading from JSONs can produce Decimal values
            counts[DataType.float] += 1
        else:
            raise ValueError(f"Value {v} has an unrecognized type: {type(v)}")

    ratios: Dict[DataType, float] = {k: v / len(values) for k, v in counts.items()}
    max_count_type = max(ratios, key=lambda k: ratios[k])

    # preliminary check: ints/floats may be loaded as strings
    if max_count_type == DataType.string:
        if string_values_are_integers(values):
            max_count_type = DataType.integer
        elif string_values_are_floats(values):
            max_count_type = DataType.float

    if max_count_type == DataType.string:
        if string_values_are_datetime(values):
            return DataType.string, FeatureType.datetime
        # is string type
        if ratio_unique >= ID_RATIO_THRESHOLD:
            # almost all unique values, i.e. either ID, text
            if multiple_separate_words_detected(values):
                return DataType.string, FeatureType.text
            else:
                if values_are_urls(values) or values_are_filepaths(values):
                    return DataType.string, FeatureType.image
                return DataType.string, FeatureType.identifier
        elif ratio_unique <= CATEGORICAL_RATIO_THRESHOLD:
            return DataType.string, FeatureType.categorical
        else:
            return DataType.string, FeatureType.text

    elif max_count_type == DataType.integer:
        if ratio_unique >= ID_RATIO_THRESHOLD:
            return DataType.integer, FeatureType.identifier
        elif ratio_unique <= CATEGORICAL_RATIO_THRESHOLD:
            return DataType.integer, FeatureType.categorical
        else:
            return DataType.integer, FeatureType.numeric
    elif max_count_type == DataType.float:
        return DataType.float, FeatureType.numeric
    elif max_count_type == DataType.boolean:
        return DataType.boolean, FeatureType.boolean
    else:
        return DataType.string, FeatureType.text


def propose_schema(
    dataset: Union[Dataset[IO[str]], Dataset[IO[bytes]]],
    name: str,
    columns: Optional[Collection[str]] = None,
    id_column: Optional[str] = None,
    modality: Optional[str] = None,
    sample_size: int = 10000,
    max_rows_checked: int = 200000,
) -> Schema:
    """
    Generates a schema for a dataset based on a sample of the dataset's rows.

    Dataset columns with no name will not be included in the schema.

    :param dataset:
    :param name: name of dataset
    :param columns: columns to generate a schema for
    :param id_column: ID column name
    :param filepath_column: filepath column name, i.e. name of column holding media filepaths (needed if modality is image)
    :param modality: data modality
    :param sample_size: default of 1000
    :param max_rows_checked: max rows to sample from
    :return:

    """
    # The arguments are intended to be required for the command-line interface, but are optional for Cleanlab Studio.
    if len(dataset) < 1:
        raise EmptyDatasetError("Cannot propose schema for empty dataset.")

    # fill optional arguments if necessary
    if columns is None:
        columns = dataset.get_columns()

    if modality is None:
        # suggested modality can be set to a media modality on line 382
        if len(columns) > 5:
            modality = Modality.tabular.value
        else:
            modality = Modality.text.value

    # dataset = []
    rows = []
    for idx, row in enumerate(dataset.read_streaming_values()):
        if idx >= max_rows_checked:
            break
        if idx < sample_size:
            rows.append(row)
        else:
            random_idx = random.randint(0, idx)
            if random_idx < sample_size:
                rows[random_idx] = row

    try:
        df = pd.DataFrame(data=rows, columns=list(columns))
    except ValueError as e:
        raise ColumnMismatchError(str(e))

    schema_dict = dict()
    fields_dict = dict()
    for column_name in columns:
        if column_name == "":
            continue
        column_values = list(df[column_name][~df[column_name].isna()])
        column_values = [v for v in column_values if v != ""]

        if len(column_values) == 0:  # all values in column are empty, give default string[text]
            fields_dict[column_name] = dict(
                data_type=DataType.string.value, feature_type=FeatureType.text.value
            )
            continue

        col_data_type, col_feature_type = infer_types(column_values)
        fields_dict[column_name] = dict(
            data_type=col_data_type.value, feature_type=col_feature_type.value
        )
        if col_feature_type in MEDIA_FEATURE_TYPES:
            modality = col_feature_type.value

    schema_dict["fields"] = fields_dict

    if id_column is None:
        id_columns = [
            k
            for k, spec in schema_dict["fields"].items()
            if spec["feature_type"] == FeatureType.identifier.value
        ]
        if len(id_columns) == 0:
            id_columns = list(columns)
        id_column = _find_best_matching_column("id", id_columns)
    else:
        if id_column not in columns:
            abort(f"ID column '{id_column}' does not exist in the dataset.")

    assert id_column is not None

    metadata: Dict[str, Optional[str]] = dict(id_column=id_column, modality=modality, name=name)
    return Schema.create(metadata=metadata, fields=fields_dict, version=SCHEMA_VERSION)


def save_schema(schema: JSONDict, filename: Optional[str]) -> None:
    """

    :param schema:
    :param filename: filename to save schema with
    :return:
    """
    if filename == "":
        filename = "schema.json"
    if filename:
        progress(f"Writing schema to {filename}...")
        dump_json(filename, schema)
        success("Saved.")
    else:
        info("Schema was not saved.")


def get_dataset_filepath_columns(
    dataset: Union[Dataset[IO[bytes]], Dataset[IO[str]]], schema: Schema
) -> List[str]:
    media_columns = [
        field_name
        for field_name, field_spec in schema.fields.items()
        if field_spec.feature_type in MEDIA_FEATURE_TYPES
    ]
    df = dataset.read_file_as_dataframe()
    return [
        col
        for col in media_columns
        if not values_are_urls(df[col]) and values_are_filepaths(df[col])
    ]
