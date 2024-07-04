"""
Tasks that involve time series whose past series contains misleading information
that can only be detected by understanding the contextual information provided
with the data.

"""

import numpy as np

from tactis.gluon.dataset import get_dataset
from gluonts.dataset.util import to_pandas

from .base import UnivariateCRPSTask
from .utils import get_random_window_univar


class PeriodicSensorMaintenanceTask(UnivariateCRPSTask):
    """
    Task that involves time series whose past series contains misleading information
    that can only be detected by understanding the contextual information provided
    with the data.

    """

    def __init__(self, fixed_config: dict = None, seed: int = None):
        super().__init__(seed=seed, fixed_config=fixed_config)

    def random_instance(self):
        datasets = ["electricity_hourly"]

        # Select a random dataset
        dataset_name = self.random.choice(datasets)
        dataset = get_dataset(dataset_name, regenerate=False)

        assert len(dataset.train) == len(
            dataset.test
        ), "Train and test sets must contain the same number of time series"

        # Get the dataset metadata
        metadata = dataset.metadata

        # Select a random time series
        ts_index = self.random.choice(len(dataset.train))
        full_series = to_pandas(list(dataset.test)[ts_index])

        # Select a random window
        window = get_random_window_univar(
            full_series,
            prediction_length=metadata.prediction_length,
            history_factor=self.random.randint(2, 5),
            random=self.random,
        )

        # Extract the history and future series
        history_series = window.iloc[: -metadata.prediction_length]
        future_series = window.iloc[-metadata.prediction_length :]

        if dataset_name == "electricity_hourly":
            # Duration: between 2 and 6 hours
            duration = self.random.randint(2, 7)
            start_hour = self.random.randint(0, 24 - duration)
            start_time = f"{start_hour:02d}:00"
            end_time = f"{(start_hour + duration):02d}:00"

            # Add the maintenance period to the window
            history_series.index = history_series.index.to_timestamp()
            history_series.loc[
                history_series.between_time(start_time, end_time).index
            ] = 0

            background = f"The sensor was offline for maintenance every day between {start_time} and {end_time}, which resulted in zero readings."

        else:
            raise NotImplementedError(
                f"Scenario for dataset {dataset_name} not implemented yet"
            )

        # Instantiate the class variables
        self.past_time = history_series
        self.future_time = future_series
        self.constraints = None
        self.background = background
        self.scenario = None
