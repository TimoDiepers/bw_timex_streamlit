import math
from datetime import datetime

import bw2data as bd
import numpy as np
import pandas as pd
import pytest
from bw2data.tests import bw2test
from bw_temporalis import TemporalDistribution

from bw_timex import TimexLCA


@pytest.fixture
@bw2test
def wastes_db():
    bd.projects.set_current("__wastes_db__")
    biosphere = bd.Database("biosphere")
    biosphere.write(
        {
            ("biosphere", "CO2"): {
                "type": "emission",
                "name": "carbon dioxide",
            },
        }
    )

    foreground = bd.Database("foreground")
    foreground.register()
    background_2020 = bd.Database("background_2020")
    background_2020.register()

    node_co2 = biosphere.get("CO2")

    fu1 = foreground.new_node("fu1", name="fu1", unit="unit")
    fu1["reference product"] = "fu1"
    fu1.save()

    fu2 = foreground.new_node("fu2", name="fu2", unit="unit")
    fu2["reference product"] = "fu2"
    fu2.save()

    fu3 = foreground.new_node("fu3", name="fu3", unit="unit")
    fu3["reference product"] = "fu3"
    fu3.save()

    some_intermediate_process = foreground.new_node(
        "some_intermediate_process", name="some_intermediate_process", unit="unit"
    )
    some_intermediate_process["reference product"] = "some_intermediate_process"
    some_intermediate_process.save()

    used_car = foreground.new_node("used_car", name="used_car", unit="unit")
    used_car["reference product"] = "used_car"
    used_car.save()

    car_treatment_2020 = background_2020.new_node(
        "car_treatment", name="car_treatment", unit="car_treatment"
    )
    car_treatment_2020["reference product"] = "car_treatment"
    car_treatment_2020.save()

    fu1.new_edge(input=fu1, amount=1, type="production").save()
    fu1.new_edge(input=used_car, amount=-1, type="technosphere").save()

    fu2.new_edge(input=fu2, amount=1, type="production").save()
    fu2.new_edge(input=some_intermediate_process, amount=-1, type="technosphere").save()

    fu3.new_edge(input=fu3, amount=1, type="production").save()
    fu3.new_edge(input=car_treatment_2020, amount=-1, type="technosphere").save()

    some_intermediate_process.new_edge(
        input=some_intermediate_process, amount=1, type="production"
    ).save()
    some_intermediate_process.new_edge(
        input=car_treatment_2020, amount=-3, type="technosphere"
    ).save()

    used_car.new_edge(input=used_car, amount=-1, type="production").save()
    used_car.new_edge(input=car_treatment_2020, amount=-3, type="technosphere").save()

    car_treatment_2020.new_edge(
        input=car_treatment_2020, amount=-1, type="production"
    ).save()
    car_treatment_2020.new_edge(input=node_co2, amount=1, type="biosphere").save()

    bd.Method(("GWP", "example")).write(
        [
            (("biosphere", "CO2"), 1),
        ]
    )


def test_signs_fu_to_car_to_treatment(wastes_db):
    method = ("GWP", "example")
    database_date_dict = {
        "background_2020": datetime.strptime("2020", "%Y"),
        "foreground": "dynamic",
    }
    fu = ("foreground", "fu1")
    tlca = TimexLCA({fu: 1}, method, database_date_dict)
    tlca.build_timeline()
    tlca.lci()
    tlca.static_lcia()

    assert math.isclose(tlca.static_lca.score, tlca.static_score, rel_tol=1e-9)


def test_signs_fu_to_intermediate_to_treatment(wastes_db):
    method = ("GWP", "example")
    database_date_dict = {
        "background_2020": datetime.strptime("2020", "%Y"),
        "foreground": "dynamic",
    }
    fu = ("foreground", "fu2")
    tlca = TimexLCA({fu: 1}, method, database_date_dict)
    tlca.build_timeline()
    tlca.lci()
    tlca.static_lcia()

    assert math.isclose(tlca.static_lca.score, tlca.static_score, rel_tol=1e-9)


def test_signs_fu_to_treatment(wastes_db):
    method = ("GWP", "example")
    database_date_dict = {
        "background_2020": datetime.strptime("2020", "%Y"),
        "foreground": "dynamic",
    }
    fu = ("foreground", "fu3")
    tlca = TimexLCA({fu: 1}, method, database_date_dict)
    tlca.build_timeline()
    tlca.lci()
    tlca.static_lcia()

    assert math.isclose(tlca.static_lca.score, tlca.static_score, rel_tol=1e-9)
