"""
Tasks based on the solar irradiance data from the NSRDB.

https://nsrdb.nrel.gov/data-viewer
"""

import datetime
import pandas as pd
import numpy as np
from abc import abstractmethod
import huggingface_hub

from ..base import UnivariateCRPSTask
from ..utils import datetime_to_str


def download_all_nsrdb_datasets(
    interval: int = 60,
) -> list[tuple[pd.Series, pd.DataFrame]]:
    """
    Download all of the NSRDB data in the HuggingFace repository for a given interval.

    Returns:
    --------
    A list which contains, for each location, the header of the data (pd.Series) and the data itself (pd.DataFrame)
    """
    fs = huggingface_hub.HfFileSystem()
    all_files = fs.ls(
        f"datasets/yatsbm/NSRDB_extract/nsrdb_{interval}_minutes", detail=False
    )
    all_files = [f.split("/")[-1] for f in all_files]

    result = []

    for hf_filename in all_files:
        local_filename = huggingface_hub.hf_hub_download(
            repo_id="yatsbm/NSRDB_extract",
            repo_type="dataset",
            filename=f"nsrdb_{interval}_minutes/{hf_filename}",
        )

        header = pd.read_csv(local_filename, nrows=1).iloc[0]
        df = pd.read_csv(local_filename, skiprows=2)
        df["datetime"] = pd.to_datetime(df[["Year", "Month", "Day", "Hour", "Minute"]])
        df = df.set_index("datetime")
        df = df.drop(columns=["Year", "Month", "Day", "Hour", "Minute"])

        # Useful to add for many tasks
        # 0 = "Clear" and 1 = "Probably Clear"
        df["Cloudy"] = ~df["Cloud Type"].isin({0, 1})

        result.append((header, df))

    return result


class BaseIrradianceFromCloudStatus(UnivariateCRPSTask):
    """
    In this task, the model is given
    """

    _context_sources = ["c_i", "c_cov"]
    # Part of the task involve understanding the impact of longer cloudy period (denser clouds)
    _skills = UnivariateCRPSTask._skills + ["reasoning: deduction"]
    __version__ = "0.0.1"  # Modification will trigger re-caching

    # Those must be overriden
    irradiance_column: str = ""
    irradiance_short_description: str = ""
    irradiance_description: str = ""

    def select_window(self) -> tuple[pd.Series, pd.DataFrame]:
        """
        Uniformly select a 3 days window amongst all of the 60 minutes files on Hugging Face,
        such that said window has enough cloudy and clear days in the history,
        and not too many switch between those to allow for a concise verbalisation.
        """
        # All lot of this work is repeated for all instances, so it wouldn't hurt to cache it.
        all_data = download_all_nsrdb_datasets(interval=60)
        valid_windows = []
        num_windows = 0
        for _, df in all_data:
            # The constraints are as follow:
            # - At least 12 cloudy hours during daytime in the first 2 days (history window)
            # - At least 4 clear hours during daytime in the first 2 days
            # - At most 15 changes of weather during the full range
            # With the current data, this gives us 388 valid windows
            valid_test = df.resample("3D").apply(
                lambda sdf: pd.Series(
                    [
                        (
                            (sdf["Cloudy"] & (sdf["Clearsky GHI"] > 0)).iloc[:48].sum()
                            >= 12
                            and (~sdf["Cloudy"] & (sdf["Clearsky GHI"] > 0))
                            .iloc[:48]
                            .sum()
                            >= 4
                            and ((sdf["Cloudy"].shift(1) != sdf["Cloudy"]).sum() <= 15)
                        ),
                        # Store the indices, to be able to recreate the sub DataFrame after selection
                        sdf.index.min(),
                        sdf.index.max(),
                    ]
                )
            )
            valid_windows.append(
                [
                    (valid_test[1].iloc[w], valid_test[2].iloc[w])
                    for w in np.nonzero(valid_test[0])[0]
                ]
            )
            num_windows += len(valid_windows[-1])

        assert (
            num_windows >= 100
        ), f"Need at least 100 valid windows, but only got {num_windows}"

        selected_window = self.random.randint(0, num_windows)
        window_count = 0
        for i in range(len(all_data)):
            if selected_window < window_count + len(valid_windows[i]):
                window = valid_windows[i][selected_window - window_count]
                header = all_data[i][0]
                # When slicing a dataframe using timestamps, the bounds are inclusive
                sub_df = all_data[i][1].loc[window[0] : window[1]]

                return header, sub_df
            window_count += len(valid_windows[i])
        raise RuntimeError(
            f"Selected a window which does not exist: {selected_window} >= {num_windows}"
        )

    def get_background(self, header: pd.Series) -> str:
        # Remove the starting "b'" and the ending "'"
        state = header["State"][2:-1]
        country = header["Country"][2:-1]
        # latitude = header["Latitude"]
        # longitude = header["Longitude"]

        # Optional: Adding latitude and longitude information
        background = f"This series contains {self.irradiance_short_description} for a location in {state}, {country}.\n"
        background += (
            f"The {self.irradiance_short_description} is {self.irradiance_description}."
        )

        return background

    def get_scenario(self, df: pd.DataFrame) -> str:
        current_state = df["Cloudy"].iloc[0]
        cloud_updates = [
            "At the beginning of the series, the weather was "
            + ("cloudy" if current_state else "clear")
            + "."
        ]
        for i in range(1, len(df)):
            new_state = df["Cloudy"].iloc[i]
            if new_state != current_state:
                current_state = new_state
                t = datetime_to_str(df.index[i])
                c = "cloudy" if new_state else "clear"
                if i < 48:
                    cloud_updates.append(f"At {t}, the weather became {c}.")
                else:
                    cloud_updates.append(
                        f"At {t}, we expect that the weather will become {c}."
                    )

        return "\n".join(cloud_updates)

    def random_instance(self):
        header, df = self.select_window()

        # history = first 48 hours, target = last 24 hours
        history_series = df[self.irradiance_column].iloc[:48]
        future_series = df[self.irradiance_column].iloc[48:]

        # Instantiate the class variables
        self.past_time = history_series.to_frame()
        self.future_time = future_series.to_frame()
        self.constraints = None
        self.background = self.get_background(header)
        self.scenario = self.get_scenario(df)

    @property
    def seasonal_period(self) -> int:
        """
        This returns the period which should be used by statistical models for this task.
        If negative, this means that the data either has no period, or the history is shorter than the period.
        """
        return 24


class GlobalHorizontalIrradianceFromCloudStatus(BaseIrradianceFromCloudStatus):
    __version__ = "0.0.1"  # Modification will trigger re-caching

    irradiance_column: str = "GHI"
    irradiance_short_description: str = "Global Horizontal Irradiance"
    irradiance_description: str = (
        "the total amount of sun energy (in Watts per squared meter) arriving on a horizontal surface"
    )


class DirectNormalIrradianceFromCloudStatus(BaseIrradianceFromCloudStatus):
    __version__ = "0.0.1"  # Modification will trigger re-caching

    irradiance_column: str = "DNI"
    irradiance_short_description: str = "Direct Normal Irradiance"
    irradiance_description: str = (
        "the total amount of sun energy (in Watts per squared meter) arriving directly from the sun on a surface perpendicular to the sunlight direction"
    )


class DiffuseHorizontalIrradianceFromCloudStatus(BaseIrradianceFromCloudStatus):
    __version__ = "0.0.1"  # Modification will trigger re-caching

    irradiance_column: str = "DHI"
    irradiance_short_description: str = "Diffuse Horizontal Irradiance"
    irradiance_description: str = (
        "the total amount of sun energy (in Watts per squared meter) arriving indirectly on a horizontal surface, ignoring the direct sunlight"
    )


__TASKS__ = [
    GlobalHorizontalIrradianceFromCloudStatus,
    DirectNormalIrradianceFromCloudStatus,
    DiffuseHorizontalIrradianceFromCloudStatus,
]