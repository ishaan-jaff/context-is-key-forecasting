import os
import pandas as pd
import requests
from io import StringIO
import json

from importlib import resources

import huggingface_hub
import datasets


from benchmark.config import DATA_STORAGE_PATH

HF_CACHE_DIR = os.environ.get("HF_HOME", os.path.join(DATA_STORAGE_PATH, "hf_cache"))

TRAFFIC_STORAGE_PATH = os.environ.get(
    "TRAFFIC_DATA_STORE", os.path.join(DATA_STORAGE_PATH, "traffic_data")
)
TRAFFIC_CSV_FILE = "traffic_merged_sensor_data.csv"
TRAFFIC_CSV_PATH = os.path.join(TRAFFIC_STORAGE_PATH, TRAFFIC_CSV_FILE)

TRAFFIC_METADATA_FILE = "traffic_metadata.json"
TRAFFIC_METADATA_PATH = os.path.join(TRAFFIC_STORAGE_PATH, TRAFFIC_METADATA_FILE)

TRAFFIC_SPLIT_PATH = os.path.join(TRAFFIC_STORAGE_PATH, "traffic_split_sensor_data")

# avoid issues where toolkit does not report memory correctly
datasets.builder.has_sufficient_disk_space = lambda needed_bytes, directory=".": True


def download_raw_traffic_data():

    # Create storage directory if it doesn't exist
    if not os.path.exists(TRAFFIC_STORAGE_PATH):
        os.makedirs(TRAFFIC_STORAGE_PATH, exist_ok=True)

    # Only download the file if it doesn't exist
    if not os.path.exists(TRAFFIC_CSV_PATH):
        huggingface_hub.hf_hub_download(
            repo_id="yatsbm/TrafficFresh",
            filename=TRAFFIC_CSV_FILE,
            repo_type="dataset",
            cache_dir=HF_CACHE_DIR,
            local_dir=TRAFFIC_STORAGE_PATH,
        )

        print(f"Data downloaded and saved to {TRAFFIC_CSV_PATH}")


def download_traffic_metadata():

    if not os.path.exists(TRAFFIC_METADATA_PATH):
        huggingface_hub.hf_hub_download(
            repo_id="yatsbm/TrafficFresh",
            filename=TRAFFIC_METADATA_FILE,
            repo_type="dataset",
            cache_dir=HF_CACHE_DIR,
            local_dir=TRAFFIC_STORAGE_PATH,
        )


def split_and_save_wide_dataframes(
    input_path=TRAFFIC_CSV_PATH,
    output_dir=TRAFFIC_SPLIT_PATH,
):
    if os.path.exists(output_dir):
        print(f"Data already split and saved to {output_dir}. Skipping split.")
        return
    # Load the combined data
    combined_data = pd.read_csv(input_path, delimiter="\t", header=0)

    # Create a directory to save the dataframes if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Iterate through each unique sensor_id
    for sensor_id in combined_data["sensor_id"].unique():
        # Filter the DataFrame for the current sensor_id
        sensor_df = combined_data[combined_data["sensor_id"] == sensor_id]

        # Define the output file name based on sensor_id
        output_file = os.path.join(output_dir, f"sensor_{sensor_id}.csv")

        # Save the wide DataFrame to a CSV file
        sensor_df.to_csv(output_file, index=False)

    print(f"Data split and saved to {output_dir}")


def download_traffic_files():
    download_raw_traffic_data()
    download_traffic_metadata()
    split_and_save_wide_dataframes()


if __name__ == "__main__":
    download_traffic_files()