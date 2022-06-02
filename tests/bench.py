from cleanlab_cli.dataset.schema_helpers import propose_schema, validate_schema
import timeit
import requests
import pytest
from cleanlab_cli.util import get_filename
import os

FILESIZES = ["1M", "10M", "100M", "1G"]
FORMATS = ["csv"]  # , "json", "xls", "xlsx"]

DATASETS = {
    "csv": {
        "1M": "https://s.anish.io/cleanlab/datasets/Tweets-1M.csv",
        "10M": "https://s.anish.io/cleanlab/datasets/Tweets-10M.csv",
        "100M": "https://s.anish.io/cleanlab/datasets/Tweets-100M.csv",
        "1G": "https://s.anish.io/cleanlab/datasets/Tweets-1G.csv",
    }
}


def download_dataset(dataset_url):
    filename = get_filename(dataset_url)
    if os.path.exists(filename):
        return
    if dataset_url.endswith(".csv"):
        req = requests.get(dataset_url)
        url_content = req.content
        with open(filename, "wb") as f:
            f.write(url_content)


@pytest.mark.parametrize("format", FORMATS)
@pytest.mark.parametrize("filesize", FILESIZES)
def test_generate_schema(benchmark, format, filesize):
    dataset_url_or_filepath = DATASETS[format][filesize]
    if dataset_url_or_filepath.startswith("http"):
        download_dataset(dataset_url_or_filepath)
        filepath = get_filename(dataset_url_or_filepath)
    else:
        filepath = dataset_url_or_filepath
    benchmark(lambda: propose_schema(filepath, id_column="tweet_id", modality="text"))


#
# def generate_schema_and_validate(filepath, id_column, modality):
#     return time_function(
#         "Propose schema", propose_schema, filepath=filepath, id_column=id_column, modality=modality
#     )
