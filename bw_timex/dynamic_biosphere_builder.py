import bw2data as bd
import numpy as np
import pandas as pd
from bw2calc import LCA
from bw_temporalis import TemporalDistribution
from scipy import sparse as sp

from .helper_classes import SetList
from .utils import convert_date_string_to_datetime, resolve_temporalized_node_name


class DynamicBiosphereBuilder:
    """
    This class is used to build a dynamic biosphere matrix, which in contrast to the normal biosphere matrix has rows for each biosphere flow at their time of emission.
    Thus, the dimensions are (bio_flows at a specific timestep) x (processes).
    """

    def __init__(
        self,
        lca_obj: LCA,
        activity_time_mapping_dict: dict,
        biosphere_time_mapping_dict: dict,
        demand_timing_dict: dict,
        node_id_collection_dict: dict,
        temporal_grouping: str,
        database_date_dict: dict,
        database_date_dict_static_only: dict,
        timeline: pd.DataFrame,
        interdatabase_activity_mapping: SetList,
        from_timeline: bool = False,
    ) -> None:
        """
        Initializes the DynamicBiosphereBuilder object.

        Parameters
        ----------
        lca_obj : LCA objecct
            instance of the bw2calc LCA class, e.g. TimexLCA.lca
        activity_time_mapping_dict : dict
            A dictionary mapping activity to their respective timing in the format (('database', 'code'), datetime_as_integer): time_mapping_id)
        biosphere_time_mapping_dict : dict
            A dictionary mapping biosphere flows to their respective timing in the format (('database', 'code'), datetime_as_integer): time_mapping_id), at this point still empty.
        demand_timing_dict : dict
            A dictionary mapping of the demand to demand time
        node_id_collection_dict : dict
            A dictionary containing lists of node ids for different node subsets
        temporal_grouping : str
            A string indicating the temporal grouping of the processes, e.g. 'year', 'month', 'day', 'hour'
        database_date_dict : dict
            A dictionary mapping database names to their respective date
        database_date_dict_static_only : dict
            A dictionary mapping database names to their respective date, but only containing static databases, which are the background databases.
        timeline: pd.DataFrame
            The edge timeline, created from TimexLCA.build_timeline()
        interdatabase_activity_mapping : SetList
            A list of sets, where each set contains the activity ids of the same activity in different databases
        from_timeline : bool, optional
            A boolean indicating if the dynamic biosphere matrix is built directly from the timeline. Default is False.

        Returns
        -------
        None

        """

        self._time_res_dict = {
            "year": "datetime64[Y]",
            "month": "datetime64[M]",
            "day": "datetime64[D]",
            "hour": "datetime64[h]",
        }

        self.lca_obj = lca_obj
        if not from_timeline:
            self.technosphere_matrix = (
                lca_obj.technosphere_matrix.tocsc()
            )  # convert to csc as this is only used for column slicing
            self.dynamic_supply_array = lca_obj.supply_array
            self.activity_dict = lca_obj.dicts.activity
        else:
            self.dynamic_supply_array = timeline.amount.values.astype(float)
        self.activity_time_mapping_dict = activity_time_mapping_dict
        self.biosphere_time_mapping_dict = biosphere_time_mapping_dict
        self.demand_timing_dict = demand_timing_dict
        self.node_id_collection_dict = node_id_collection_dict
        self.time_res = self._time_res_dict[temporal_grouping]
        self.temporal_grouping = temporal_grouping
        self.database_date_dict = database_date_dict
        self.database_date_dict_static_only = database_date_dict_static_only
        self.timeline = timeline
        self.interdatabase_activity_mapping = interdatabase_activity_mapping
        self.rows = []
        self.cols = []
        self.values = []
        self.unique_rows_cols = set()  # To keep track of (row, col) pairs

    def build_dynamic_biosphere_matrix(
        self,
        from_timeline: bool = False,
    ):
        """
        This function creates a separate biosphere matrix, with the dimenions (bio_flows at a specific timestep) x (processes).
        Every temporally resolved biosphere flow has its own row in the matrix, making it highly sparse.
        The timing of the emitting process and potential additional temporal information of the bioshpere flow (e.g. delay of emission compared to timing of process) are considered.

        Absolute Temporal Distributions for biosphere exchanges are dealt with as a look up function:
        If an activity happens at timestamp X then and the biosphere exchange has an absolute temporal
        distribution (ATD), it looks up the amount from from the ATD correspnding to timestamp X.
        E.g.: X = 2024, TD=(data=[2020,2021,2022,2023,2024,.....,2120 ], amount=[3,4,4,5,6,......,3]),
        it will look up the value 6 corresponding 2024. If timestamp X does not exist it find the nearest
        timestamp available (if two timestamps are equally close, it will take the first in order of
        apearance (see numpy.argmin() for this behabiour).


        Parameters
        ----------
        from_timeline

        Returns
        -------
        dynamic_biomatrix : scipy.sparse.csr_matrix
            A sparse matrix with the dimensions (bio_flows at a specific timestep) x (processes), where every row represents a biosphere flow at a specific time.
        """

        for row in self.timeline.itertuples():
            idx = row.time_mapped_producer
            if from_timeline:
                process_col_index = row.Index
            else:
                process_col_index = self.activity_dict[
                    idx
                ]  # get the matrix column index

            (
                (original_db, original_code),
                time,
            ) = self.activity_time_mapping_dict.reversed()[  # time is here an integer, with various length depending on temporal grouping, e.g. [Y] -> 2024, [M] - > 202401
                idx
            ]

            if idx in self.node_id_collection_dict["temporalized_processes"]:

                time_in_datetime = convert_date_string_to_datetime(
                    self.temporal_grouping, str(time)
                )  # now time is a datetime

                td_producer = TemporalDistribution(
                    date=np.array([time_in_datetime], dtype=self.time_res),
                    amount=np.array([1]),
                ).date
                date = td_producer[0]

                if original_db == "temporalized":
                    act = bd.get_node(code=original_code)
                else:
                    act = bd.get_node(database=original_db, code=original_code)

                for exc in act.biosphere():
                    if exc.get("temporal_distribution"):
                        td_dates = exc["temporal_distribution"].date
                        td_values = exc["temporal_distribution"].amount
                        if (
                            type(td_dates[0]) == np.datetime64
                        ):  # If the biosphere flows have an absolute TD, this means we have to look up the biosphere flow for the activity time (td_producer)
                            dates = td_producer  # datetime array, same time as producer
                            values = [
                                exc["amount"]
                                * td_values[
                                    np.argmin(
                                        np.abs(
                                            td_dates.astype(self.time_res)
                                            - td_producer.astype(self.time_res)
                                        )
                                    )
                                ]
                            ]  # look up the value correponding to the absolute producer time
                        else:
                            dates = (
                                td_producer + td_dates
                            )  # we can add a datetime of length 1 to a timedelta of length N without problems
                            values = exc["amount"] * td_values

                    else:  # exchange has no TD
                        dates = td_producer  # datetime array, same time as producer
                        values = [exc["amount"]]

                    # Add entries to dynamic bio matrix
                    for date, amount in zip(dates, values):

                        # first create a row index for the tuple((db, bioflow), date))
                        time_mapped_matrix_id = self.biosphere_time_mapping_dict.add(
                            (exc.input.id, date)
                        )

                        # populate lists with which sparse matrix is constructed
                        self.add_matrix_entry_for_biosphere_flows(
                            row=time_mapped_matrix_id,
                            col=process_col_index,
                            amount=amount,
                        )
            elif idx in self.node_id_collection_dict["temporal_markets"]:
                (
                    (original_db, original_code),
                    time,
                ) = self.activity_time_mapping_dict.reversed()[  # time is here an integer, with various length depending on temporal grouping, e.g. [Y] -> 2024, [M] - > 202401
                    idx
                ]

                if from_timeline:
                    demand = self.demand_from_timeline(row, original_db)
                else:
                    demand = self.demand_from_technosphere(idx, process_col_index)

                if demand:
                    self.lca_obj.redo_lci(demand)

                    aggregated_inventory = self.lca_obj.inventory.sum(
                        axis=1
                    )  # aggregated biosphere flows of background supply chain emissions. Rows are bioflows.

                    for row_idx, amount in enumerate(aggregated_inventory.A1):
                        bioflow = self.lca_obj.dicts.biosphere.reversed[row_idx]
                        ((_, _), time) = self.activity_time_mapping_dict.reversed()[idx]

                        time_in_datetime = convert_date_string_to_datetime(
                            self.temporal_grouping, str(time)
                        )  # now time is a datetime

                        td_producer = TemporalDistribution(
                            date=np.array([str(time_in_datetime)], dtype=self.time_res),
                            amount=np.array([1]),
                        ).date  # TODO: Simplify
                        date = td_producer[0]

                        time_mapped_matrix_id = self.biosphere_time_mapping_dict.add(
                            (bioflow, date)
                        )

                        self.add_matrix_entry_for_biosphere_flows(
                            row=time_mapped_matrix_id,
                            col=process_col_index,
                            amount=amount,
                        )

        # now build the dynamic biosphere matrix
        if from_timeline:
            ncols = len(self.timeline)
        else:
            ncols = len(self.activity_time_mapping_dict)
        shape = (max(self.rows) + 1, ncols)
        dynamic_biomatrix = sp.coo_matrix((self.values, (self.rows, self.cols)), shape)
        self.dynamic_biomatrix = dynamic_biomatrix.tocsr()

        return self.dynamic_biomatrix

    def demand_from_timeline(self, row, original_db):
        """
        Returns a demand dict directly from the timeline row
        and its interpolation_weights.
        """
        demand = {}
        for db, amount in row.interpolation_weights.items():
            # if not db in act_time_combinations.get(original_code):  #check if act time combination already exists
            [(timed_act_id, _)] = [
                (act, db_name)
                for (act, db_name) in self.interdatabase_activity_mapping[
                    (row.producer, original_db)
                ]
                if db == db_name
            ]
            # t_act = bd.get_activity(timed_act_id)
            demand[timed_act_id] = amount
        return demand

    def demand_from_technosphere(self, idx, process_col_index):
        """
        Returns a demand dict based on the technosphere colummn.
        """
        technosphere_column = (
            self.technosphere_matrix[:, process_col_index].toarray().ravel()
        )  # 1-d np.array
        demand = {}
        for row_idx, amount in enumerate(technosphere_column):
            if row_idx == self.activity_dict[idx]:  # Skip production exchange
                continue
            if amount == 0:
                continue

            node_id = self.activity_dict.reversed[row_idx]

            if (
                node_id in self.node_id_collection_dict["foreground_node_ids"]
            ):  # We only aggregate background process bioflows
                continue

            # demand[bd.get_node(id=node_id)] = -amount
            demand[node_id] = -amount
        return demand

    def add_matrix_entry_for_biosphere_flows(self, row, col, amount):
        """
        Adds an entry to the lists of row, col and values, which are then used to construct the dynamic biosphere matrix.
        Only unqiue entries are added, i.e. if the same row and col index already exists, the value is not added again.

        Parameters
        ----------
        row : int
            A row index of a new element to the dynamic biosphere matrix
        col: int
            A column index of a new element to the dynamic biosphere matrix
        amount: float
            The amount of the new element to the dynamic biosphere matrix

        Returns
        -------
        None, but the lists of row, col and values are updated

        """

        if (row, col) not in self.unique_rows_cols:
            self.rows.append(row)
            self.cols.append(col)
            self.values.append(amount)

            self.unique_rows_cols.add((row, col))
