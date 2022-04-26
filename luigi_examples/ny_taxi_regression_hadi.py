import luigi
import numpy as np
import pandas as pd
import json
from pickle import dump
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import OneHotEncoder
from xgboost import XGBRegressor
from inhabitation_task import LuigiCombinator, ClsParameter, RepoMeta
from cls_python import FiniteCombinatoryLogic, Subtypes
from cls_luigi_read_tabular_data import WriteSetupJson, ReadTabularData


class WriteCSVRegressionSetupJson(WriteSetupJson):
    abstract = False

    def run(self):
        d = {
            "csv_file": "data/taxy_trips_ny_2016-06-01to03_3%sample.csv",
            "date_column": ['pickup_datetime', 'dropoff_datetime'],
            # "temperature_column": ["max_temp", "min_temp"],
            "drop_column": ["rain", "has_rain", "main_street",
                            "main_street_ratio", "trip_distance",
                            'pickup_datetime', 'dropoff_datetime',
                            'vendor_id', "passenger_count", "max_temp", "min_temp"],
            "target_column": 'trip_duration',
            "seed": 42
        }
        with open(self.output().path, 'w') as f:
            json.dump(d, f, indent=4)


class ReadTaxiData(ReadTabularData):
    abstract = False

    def run(self):
        setup = self._read_setup()
        taxi = pd.read_csv(setup["csv_file"], parse_dates=setup["date_column"])
        taxi.to_pickle(self.output().path)


class InitialCleaning(luigi.Task, LuigiCombinator):
    abstract = False
    tabular_data = ClsParameter(tpe=ReadTaxiData.return_type())

    def requires(self):
        return [self.tabular_data()]

    def run(self):
        taxi = pd.read_pickle(self.input()[0].open().name)
        print("Taxi DataFrame shape before dropping NaNs and duplicates", taxi.shape)
        taxi = taxi.dropna().drop_duplicates()
        print("Taxi DataFrame shape after dropping NaNs and duplicates", taxi.shape)
        taxi.to_pickle(self.output().path)

    def output(self):
        return luigi.LocalTarget('data/cleaned_data.pkl')


class FilterImplausibleTrips(luigi.Task, LuigiCombinator):
    abstract = False

    clean_data = ClsParameter(tpe=InitialCleaning.return_type())
    setup = ClsParameter(tpe=WriteCSVRegressionSetupJson.return_type())

    def requires(self):
        return [self.clean_data(), self.setup()]

    def _read_setup(self):
        with open(self.input()[1].open().name) as file:
            setup = json.load(file)
        return setup

    def run(self):
        setup = self._read_setup()
        taxi = pd.read_pickle(self.input()[0].open().name)
        taxi = taxi[
            (taxi[setup["target_column"]] >= 10) &
            (taxi[setup["target_column"]] <= 100000)
            ]
        print("Taxi DataFrame shape after filtering implausible trips", taxi.shape)
        taxi.to_pickle(self.output().path)

    def output(self):
        return luigi.LocalTarget('data/filtered_trips.pkl')


class ExtractRawTemporalFeatures(luigi.Task, LuigiCombinator):
    abstract = False
    filtered_tabular_data = ClsParameter(tpe=FilterImplausibleTrips.return_type())
    setup = ClsParameter(tpe=WriteCSVRegressionSetupJson.return_type())

    def requires(self):
        return [self.filtered_tabular_data(), self.setup()]

    def _read_setup(self):
        with open('data/setup.json') as file:
            setup = json.load(file)
        return setup

    def _read_tabular_data(self):
        return pd.read_pickle(self.input()[0].open().name)

    def run(self):
        setup = self._read_setup()
        tabular = self._read_tabular_data()
        raw_temporal_features = pd.DataFrame(index=tabular.index)
        for c in setup["date_column"]:
            print("Preprocessing Datetime-Column:", c)
            raw_temporal_features[c + "_YEAR"] = tabular[c].dt.year
            raw_temporal_features[c + "_MONTH"] = tabular[c].dt.hour
            raw_temporal_features[c + "_DAY"] = tabular[c].dt.day
            raw_temporal_features[c + "_WEEKDAY"] = tabular[c].dt.dayofweek
            raw_temporal_features[c + "_HOUR"] = tabular[c].dt.hour

        raw_temporal_features.to_pickle(self.output().path)

    def output(self):
        return luigi.LocalTarget('data/raw_temporal_features.pkl')


class BinaryEncodePickupIsInWeekend(luigi.Task, LuigiCombinator):
    abstract = False
    raw_temporal_data = ClsParameter(tpe=ExtractRawTemporalFeatures.return_type())

    def requires(self):
        return [self.raw_temporal_data()]

    def _read_tabular_data(self):
        return pd.read_pickle(self.input()[0].open().name)

    def run(self):
        raw_temporal_data = self._read_tabular_data()
        df_is_weekend = pd.DataFrame(index=raw_temporal_data.index)

        def weekend_mapping(weekday):
            if weekday >= 5:
                return 1
            return 0

        df_is_weekend["is_weekend"] = raw_temporal_data["pickup_datetime_WEEKDAY"].map(
            weekend_mapping)
        df_is_weekend.to_pickle(self.output().path)

    def output(self):
        return luigi.LocalTarget('data/is_weekend.pkl')


class BinaryEncodePickupIsAtHour(luigi.Task, LuigiCombinator):
    abstract = False
    raw_temporal_data = ClsParameter(tpe=ExtractRawTemporalFeatures.return_type())
    hour = luigi.IntParameter(default=7)

    def requires(self):
        return [self.raw_temporal_data()]

    def _read_tabular_data(self):
        return pd.read_pickle(self.input()[0].open().name)

    def run(self):
        raw_temporal_data = self._read_tabular_data()
        df_pickup_hour_encoded = pd.DataFrame(index=raw_temporal_data.index)

        def pickup_hour_mapper(hour):
            if hour >= self.hour:
                return 1
            return 0

        col_name = "is after_" + str(self.hour)
        df_pickup_hour_encoded[col_name] = raw_temporal_data["pickup_datetime_HOUR"].map(
            pickup_hour_mapper)
        df_pickup_hour_encoded.to_pickle(self.output().path)

    def output(self):
        return luigi.LocalTarget('data/pickup_hour.pkl')


class EncodePickupWeekdayOneHotSklearn(luigi.Task, LuigiCombinator):
    abstract = False
    raw_temporal_data = ClsParameter(tpe=ExtractRawTemporalFeatures.return_type())

    def requires(self):
        return [self.raw_temporal_data()]

    def _read_tabular_data(self):
        return pd.read_pickle(self.input()[0].open().name)

    def run(self):
        raw_temporal_data = self._read_tabular_data()

        def map_weekday_num_to_name(weekday_num):
            weekdays = {
                0: "Monday",
                1: "Tuesday",
                2: "Wednesday",
                3: "Thursday",
                4: "Friday",
                5: "Saturday",
                6: "Sunday"
            }
            return "pickup " + weekdays[weekday_num]

        raw_temporal_data["pickup_datetime_WEEKDAY"] = raw_temporal_data["pickup_datetime_WEEKDAY"].map(
            map_weekday_num_to_name
        )
        transformer = OneHotEncoder(sparse=False)
        encoded_features = transformer.fit_transform(raw_temporal_data[["pickup_datetime_WEEKDAY"]])

        category_columns = np.concatenate(transformer.categories_)
        onehot_weekdays = pd.DataFrame(
            encoded_features,
            columns=category_columns,
            index=raw_temporal_data.index)

        onehot_weekdays.to_pickle(self.output().path)

    def output(self):
        return luigi.LocalTarget('data/one_hot_weekday.pkl')


class DummyEncodingNode(BinaryEncodePickupIsInWeekend,
                        EncodePickupWeekdayOneHotSklearn):
    abstract = False

    def run(self):
        with open(self.output().path, "w") as f:
            f.write("dummy")

    def output(self):
        return luigi.LocalTarget('data/dummy.txt')


s = {BinaryEncodePickupIsInWeekend,
     EncodePickupWeekdayOneHotSklearn}


class ExtractFeatures(luigi.Task, LuigiCombinator):
    abstract = False
    filtered_trips = ClsParameter(tpe=FilterImplausibleTrips.return_type())
    raw_temporal_features = ClsParameter(tpe=ExtractRawTemporalFeatures.return_type())

    is_after_7am = ClsParameter(tpe=BinaryEncodePickupIsAtHour.return_type())

    is_weekend = ClsParameter(tpe=BinaryEncodePickupIsInWeekend.return_type() \
        if BinaryEncodePickupIsInWeekend in s else DummyEncodingNode.return_type())

    onehot_weekdays = ClsParameter(tpe=EncodePickupWeekdayOneHotSklearn.return_type() \
        if EncodePickupWeekdayOneHotSklearn in s else DummyEncodingNode.return_type())

    def requires(self):
        return [self.filtered_trips(), self.raw_temporal_features(),
                self.is_weekend(), self.is_after_7am(7), self.onehot_weekdays()]

    def output(self):
        return self.input()


class JoinAndFilterFeatures(luigi.Task, LuigiCombinator):
    abstract = False
    extracted = ClsParameter(tpe=ExtractFeatures.return_type())
    var_ix = luigi.IntParameter()

    def requires(self):
        return self.extracted()

    def _read_setup(self):
        with open('data/setup.json') as file:
            setup = json.load(file)
        return setup

    def run(self):
        setup = self._read_setup()
        df_joined = None
        for i in self.input():
            path = i.open().name
            if path != 'data/dummy.txt':
                if df_joined is None:
                    df_joined = pd.read_pickle(path)
                else:
                    data = pd.read_pickle(path)
                    df_joined = pd.merge(df_joined, data, left_index=True, right_index=True)

        if len(setup["drop_column"]) != 0:
            df_joined = df_joined.drop(setup["drop_column"], axis="columns")
        df_joined.to_pickle(self.output().path)

    def output(self):
        return luigi.LocalTarget("data/processed_data_" + str(self.var_ix) + ".pkl")


class TrainRegressionModel(luigi.Task, LuigiCombinator):
    abstract = True
    preprocessed_filtered = ClsParameter(tpe=JoinAndFilterFeatures.return_type())
    setup = ClsParameter(tpe=WriteSetupJson.return_type())
    var_ix = luigi.IntParameter()

    def requires(self):
        return [self.preprocessed_filtered(self.var_ix), self.setup()]

    def _read_setup(self):
        with open(self.input()[1].open().name) as file:
            setup = json.load(file)
        return setup

    def _read_tabular_data(self):
        return pd.read_pickle(self.input()[0].open().name)


class TrainLinearRegressionModel(TrainRegressionModel):
    abstract = False

    def run(self):
        setup = self._read_setup()
        tabular = self._read_tabular_data()
        print("TARGET:", setup["target_column"])
        print("NOW WE FIT LINEAR REGRESSION MODEL")

        X = tabular.drop(setup["target_column"], axis="columns")
        y = tabular[[setup["target_column"]]].values.ravel()
        print("WITH THE FEATURES")
        print(X.columns)
        print(X)
        print(X.shape)
        print("AND Target")
        print(y)
        print(y.shape)
        reg = LinearRegression().fit(X, y)

        print(reg.coef_)

        with open(self.output().path, 'wb') as f:
            dump(reg, f)

    def output(self):
        return luigi.LocalTarget(
            'data/linear_reg_model_var_' + str(self.var_ix) + '.pkl')


class TrainRandomForestModel(TrainRegressionModel):
    abstract = False

    def run(self):
        setup = self._read_setup()
        tabular = self._read_tabular_data()
        print("TARGET:", setup["target_column"])
        print("NOW WE FIT RANDOM FOREST MODEL")

        X = tabular.drop(setup["target_column"], axis="columns")
        y = tabular[[setup["target_column"]]].values.ravel()
        print("WITH THE FEATURES")
        print(X.columns)
        print(X)
        print(X.shape)
        print("AND Target")
        print(y)
        print(y.shape)
        rfr = RandomForestRegressor(random_state=setup["seed"]).fit(X, y)

        with open(self.output().path, 'wb') as f:
            dump(rfr, f)

    def output(self):
        return luigi.LocalTarget('data/random_forest_reg_model_var_' + str(self.var_ix) + '.pkl')


class TrainXgBoostModel(TrainRegressionModel):
    abstract = False

    def run(self):
        setup = self._read_setup()
        tabular = self._read_tabular_data()
        print("TARGET:", setup["target_column"])
        print("NOW WE FIT XGBOOST MODEL")

        X = tabular.drop(setup["target_column"], axis="columns")
        y = tabular[[setup["target_column"]]].values.ravel()
        print("WITH THE FEATURES")
        print(X.columns)
        print(X)
        print(X.shape)
        print("AND Target")
        print(y)
        print(y.shape)
        xgb = XGBRegressor(random_state=setup["seed"]).fit(X, y)

        with open(self.output().path, 'wb') as f:
            dump(xgb, f)

    def output(self):
        return luigi.LocalTarget('data/xgboost_reg_model_var_' + str(self.var_ix) + '.pkl')


class FinalNode(luigi.WrapperTask, LuigiCombinator):
    train = ClsParameter(tpe=TrainRegressionModel.return_type())

    def requires(self):
        return self.train(self.config_index)


if __name__ == '__main__':
    target = FinalNode.return_type()
    print("Collecting Repo")
    repository = RepoMeta.repository
    print("Build Repository...")
    fcl = FiniteCombinatoryLogic(repository, Subtypes(RepoMeta.subtypes), processes=1)
    print("Build Tree Grammar and inhabit Pipelines...")

    inhabitation_result = fcl.inhabit(target)
    print("Enumerating results...")
    max_tasks_when_infinite = 10
    actual = inhabitation_result.size()
    max_results = max_tasks_when_infinite
    if actual > 0:
        max_results = actual
    results = [t() for t in inhabitation_result.evaluated[0:max_results]]
    for var_ix, r in enumerate(results):
        r.config_index = var_ix
    if results:
        print("Number of results", max_results)
        print("Run Pipelines")
        luigi.build(results, local_scheduler=False)
    else:
        print("No results!")
