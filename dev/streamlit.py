import streamlit as st
from streamlit_ace import st_ace
import streamlit_mermaid as stmd

import os

if not os.path.exists("/tmp/"):
    os.mkdir("/tmp/")
import os
os.environ["BRIGHTWAY_DIR"] = "/tmp/"

st.title('Hello, Streamlit!')

# mermaid_chart ="""
# flowchart LR
# subgraph background[<i>background</i>]
#     B(Process B):::bg
# end

# subgraph foreground[<i>foreground</i>]
#     A(Process A):::fg
# end

# subgraph biosphere[<i>biosphere</i>]
#     CO2(CO2):::bio
# end

# B-->|"3 kg"|A
# A-.->|"5 kg"|CO2
# B-.->|"11 kg"|CO2

# style background fill:none, stroke:none;
# style foreground fill:none, stroke:none;
# style biosphere fill:none, stroke:none;
# """
# stmd.st_mermaid(mermaid_chart)

import bw2data as bd
import numpy as np
from datetime import datetime
from bw_temporalis import TemporalDistribution
from bw_timex.utils import add_temporal_distribution_to_exchange

bd.projects.set_current("getting_started_with_timex")

default_code = """bd.Database("biosphere").write(
    {
        ("biosphere", "CO2"): {
            "type": "emission",
            "name": "CO2",
        },
    }
)

bd.Database("background").write(
    {
        ("background", "B"): {
            "name": "B",
            "location": "somewhere",
            "reference product": "B",
            "exchanges": [
                {
                    "amount": 1,
                    "type": "production",
                    "input": ("background", "B"),
                },
                {
                    "amount": 11,
                    "type": "biosphere",
                    "input": ("biosphere", "CO2"),
                },
            ],
        },
    }
)

bd.Database("foreground").write(
    {
        ("foreground", "A"): {
            "name": "A",
            "location": "somewhere",
            "reference product": "A",
            "exchanges": [
                {
                    "amount": 1,
                    "type": "production",
                    "input": ("foreground", "A"),
                },
                {
                    "amount": 3,
                    "type": "technosphere",
                    "input": ("background", "B"),
                },
                {
                    "amount": 5,
                    "type": "biosphere",
                    "input": ("biosphere", "CO2"),
                }
            ],
        },
    }
)

bd.Database("background_2030").write(
    {
        ("background_2030", "B"): {
            "name": "B",
            "location": "somewhere",
            "reference product": "B",
            "exchanges": [
                {
                    "amount": 1,
                    "type": "production",
                    "input": ("background_2030", "B"),
                },
                {
                    "amount": 7,
                    "type": "biosphere",
                    "input": ("biosphere", "CO2"),
                },
            ],
        },
    }
)

bd.Method(("our", "method")).write(
    [
        (("biosphere", "CO2"), 1),
    ]
)

td_b_to_a = TemporalDistribution(
    date=np.array([-2, 0, 4], dtype="timedelta64[Y]"),
    amount=np.array([0.3, 0.5, 0.2]),
)

add_temporal_distribution_to_exchange(
    temporal_distribution=td_b_to_a, 
    input_code="B", 
    input_database="background",
    output_code="A",
    output_database="foreground"
)

td_a_to_co2 = TemporalDistribution(
    date=np.array([0, 1], dtype="timedelta64[Y]"),
    amount=np.array([0.6, 0.4]),
)

add_temporal_distribution_to_exchange(
    temporal_distribution=td_a_to_co2, 
    input_code="CO2", 
    output_code="A"
)

database_date_dict = {
    "background": datetime.strptime("2020", "%Y"),
    "background_2030": datetime.strptime("2030", "%Y"),
    "foreground": "dynamic",
}

demand = {("foreground", "A"): 1}
method = ("our", "method")
"""

def calculate_results():
    with st.spinner("thinking..."):

        from bw_timex import TimexLCA

        tlca = TimexLCA(
            demand=demand,
            method=method,
            database_date_dict=database_date_dict,
        )

        timeline = tlca.build_timeline()

        st.dataframe(timeline)

        tlca.lci()
        tlca.static_lcia()
        st.write("Static score: ", tlca.static_score)

        from dynamic_characterization.timex import characterize_co2
        emission_id = bd.get_activity(("biosphere", "CO2")).id

        characterization_function_dict = {
            emission_id: characterize_co2,
        }

        def plot_characterized_inventory(tlca):
            from bw_timex.utils import resolve_temporalized_node_name
            # Prepare the plot data
            metric_ylabels = {
                "radiative_forcing": "radiative forcing [W/m²]",
                "GWP": f"GWP{tlca.current_time_horizon} [kg CO₂-eq]",
            }

            plot_data = tlca.characterized_inventory.copy()

            # Sum emissions within activities
            plot_data = plot_data.groupby(["date", "activity"]).sum().reset_index()
            plot_data["amount_sum"] = plot_data["amount"].cumsum()

            # Create a mapping for activity names
            activity_name_cache = {}
            for activity in plot_data["activity"].unique():
                if activity not in activity_name_cache:
                    activity_name_cache[activity] = resolve_temporalized_node_name(
                        tlca.activity_time_mapping_dict_reversed[activity][0][1]
                    )
            plot_data["activity_label"] = plot_data["activity"].map(activity_name_cache)

            # Create a wide-form DataFrame suitable for st.scatter_chart
            # We'll pivot the table so each activity is a separate column
            plot_data_wide = plot_data.pivot(index="date", columns="activity_label", values="amount")

            # Plot using Streamlit's st.scatter_chart
            st.scatter_chart(plot_data_wide, x_label="time", y_label=metric_ylabels[tlca.current_metric], size=40)

        tlca.dynamic_lcia(
            metric="radiative_forcing",
            time_horizon=100,
            characterization_function_dict=characterization_function_dict,
        )

        plot_characterized_inventory(tlca)

        tlca.dynamic_lcia(
            metric="GWP",
            time_horizon=100,
            characterization_function_dict=characterization_function_dict,
        )

        plot_characterized_inventory(tlca)

# Create the ACE editor with default code
code = st_ace(value=default_code, language='python', height=400, wrap=True, font_size=12, theme="tomorrow_night_bright")

# Button to execute the code
if code:
    try:
        # Execute the user's code
        exec(code)
        calculate_results()
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.warning("Please enter some code.")
