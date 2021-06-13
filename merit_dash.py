import altair as alt
import folium
import pandas as pd
import panel as pn
import param

alt.data_transformers.disable_max_rows()

# Load Template
with open("template.html", "r") as t:
    template = t.read().replace("\n", "")

df1 = pd.read_csv("data/conventional_power_plants_EU.csv")
df_params = pd.read_csv("data/parameters.csv", index_col=0)
df_dem = pd.read_csv("data/demand_stats.csv", index_col=0)

COLORS = {
    "Hydro Pumped Storage": "teal",
    "Hydro Water Reservoir": "teal",
    "Hydro Run-of-river and poundage": "cyan",
    "Hydro": "teal",
    "Wind Onshore": "blue",
    "Wind Offshore": "blue",
    "Nuclear": "purple",
    "Solar": "yellow",
    "Biomass": "forestgreen",
    "Waste": "darkgreen",
    "Geothermal": "olive",
    "Natural Gas": "grey",
    "Fossil Coal-derived gas": "grey",
    "Lignite": "brown",
    "Hard coal": "brown",
    "Fossil Peat": "brown",
    "Fossil Oil shale": "red",
    "Fossil Oil": "red",
    "Other": "whitesmoke",
    "Marine": "steelblue",
    "Biomass and biogas": "darkseagreen",
    "Fossil Coal-derived gas": "dimgrey",
    "Oil": "red",
    "Bioenergy": "forestgreen",
    "Non-renewable waste": "darkgreen",
    "Mixed fossil fuels": "khaki",
    "Other or unspecified energy sources": "orchid",
    "Other fossil fuels": "wheat",
    "Other fuels": "lavender",
    "Natural Gas": "gold",
}


class Merit_dash(param.Parameterized):

    countries = param.ListSelector(
        ["DE"], objects=(sorted(df1["country"].unique()))  # , height_policy="max"
    )

    carbon_price = param.Number(0, bounds=(0, 100))
    toggle_operation = param.ObjectSelector(
        default="Full capacity", objects=["Full capacity", "Average day"]
    )
    toggle_aggregate_by_type = param.Boolean(default=True)
    button = param.Action(lambda x: x.param.trigger("button"), label="Reset values")

    # Generate parameters for fuel prices
    par_price_dict = {}
    par_price_dict_default = {}
    for ind, par in df_params.iterrows():
        par_price_dict_default[ind] = par["Cost (EUR/Mwh)"]
        par_price_dict[ind] = param.Number(par["Cost (EUR/Mwh)"], bounds=(0, 100))
    # Assign to variables so that params are properly embedded in object
    # https://stackoverflow.com/questions/18090672/convert-dictionary-entries-into-variables-python
    locals().update(par_price_dict)
    price_params = list(par_price_dict.keys())

    def __init__(self, **params):
        super().__init__(**params)
        # In init we define layout of the dashboard
        widgets_plot = pn.Param(
            self.param,
            parameters=["countries", "toggle_operation", "carbon_price"],
            show_name=True,
            widgets={
                "carbon_price": {
                    "type": pn.widgets.FloatSlider,
                    "name": "Carbon price (EUR per tonne)",
                },
                "toggle_operation": {
                    "type": pn.widgets.RadioBoxGroup,
                    "name": "Operation type",
                    "inline": True,
                },
                "countries": {
                    "type": pn.widgets.MultiSelect,
                    "name": "Countries:",
                    "height": 450,
                },
            },
        )

        widget_prices = pn.Column(
            self.param["button"],
            pn.Param(self.param, parameters=self.price_params, show_name=True),
        )
        widgets = pn.Tabs(
            ("Plot parameters", pn.WidgetBox(widgets_plot)),
            ("Fuel Prices (EUR/MWh)", widget_prices),
        )
        results = pn.Tabs(
            ("Merit order", self.plot_merit_order_altair),
            ("Map", self.heatmap),
            (
                "Capacities",
                pn.Column(self.param["toggle_aggregate_by_type"], self.capacities),
            ),
        )
        self.view = pn.Row(widgets, results)

    def q_df(self):
        df_filtered = df1[df1["country"].isin(self.countries)]
        self.update_prices()  #  This is not very efficient as it is changing the mutable dataframe and the remerges FIXME
        df_merged = pd.merge(df_filtered, df_params, on="energy_source")
        df_merged["marg_cost"] = (df_merged["Cost (EUR/Mwh)"] / df_merged["eff"]).round(
            2
        )
        df_merged = df_merged.dropna(subset=["marg_cost"]).sort_values("marg_cost")
        return df_merged

    def update_prices(self):
        prices = [getattr(self, par) * 1.0 for par in self.price_params]
        df_params.loc[self.price_params, "Cost (EUR/Mwh)"] = prices

    @param.depends("button", watch=True)
    def reset_prices(self):
        for par in self.price_params:
            setattr(self, par, self.par_price_dict_default[par])
        self.plot_merit_order_altair()

    @param.depends("countries", "carbon_price", "toggle_operation", *price_params)
    def plot_merit_order_altair(self):
        df_merged = self.q_df()
        df_merged["marg_cost"] += (
            (df_merged["Emissions (gr/kWh)"] / df_merged["eff"])
            / 1000
            * self.carbon_price
        ).round(2)
        df_merged = df_merged.sort_values("marg_cost")
        # Modify the capacity (Full or average ?)
        if self.toggle_operation == "Average day":
            df_merged["capacity_plot"] = (
                df_merged["capacity"] * df_merged["Capacity Factor"]
            )
        else:
            df_merged["capacity_plot"] = df_merged["capacity"]
        df_merged["x1"] = df_merged["capacity_plot"].cumsum() / 1e3
        df_merged["x2"] = df_merged["x1"].shift(fill_value=0).values

        power = (
            alt.Chart(df_merged)
            .mark_rect()
            .encode(
                x=alt.X("x1:Q", title="Capacity (GW)"),
                x2="x2",
                y=alt.Y("marg_cost:Q", title="Marginal Cost (EUR/MWh)"),
                color=alt.Color(
                    "energy_source:N",
                    scale=alt.Scale(
                        domain=list(COLORS.keys()), range=list(COLORS.values())
                    ),
                    legend=alt.Legend(title="Technology"),
                ),
                tooltip=["name", "energy_source", "capacity", "marg_cost"],
            )
        )
        chart = power
        # Show demand bands only for one country
        if False and len(self.countries) == 1 and self.countries[0] in df_dem.index:
            df_demp = df_dem.loc[self.countries[0]].to_frame().T
            demand = (
                alt.Chart(df_demp)
                .mark_rect(opacity=0.3, color="grey")
                .encode(x="min:Q", x2="max:Q")
            )
            chart = demand + power

        return (
            chart.properties(width=550, height=500)
            .configure_axis(grid=False)
            .configure_view(strokeWidth=1)
        )

    @param.depends("countries")
    def heatmap(self):
         # IMPORTANT: add map to a folium Figure
        # return a figure with a set width/height
        figure = folium.Figure(width=700, height=700)

        return pn.Pane(figure)

    @param.depends("countries", "toggle_aggregate_by_type")
    def capacities(self):
        df_filtered = df1[df1["country"].isin(self.countries)]
        if not self.toggle_aggregate_by_type:
            df_out = df_filtered[["name", "energy_source", "capacity"]].set_index("name")
        else:
            df_out = df_filtered.groupby("energy_source")["capacity"].sum().to_frame()
        # df_out.index.name = None
        return pn.widgets.DataFrame(df_out.round(1))


# Example tabs no reload: https://nbviewer.jupyter.org/urls/discourse.holoviz.org/uploads/short-url/a7HodbaxdEsiUXyiIRUt8gpfkAG.ipynb
a = Merit_dash(name="")

tmpl = pn.Template(template)

tmpl.add_panel("A", a.view)
tmpl.servable(title="Merit order")
