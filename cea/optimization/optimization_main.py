"""
multi-objective optimization of supply systems for the CEA
"""

from __future__ import division
import os
import pandas as pd
import cea.config
import cea.globalvar
import cea.inputlocator
from cea.optimization.prices import Prices as Prices
import cea.optimization.distribution.network_opt_main as network_opt
import cea.optimization.master.master_main as master
from cea.optimization.preprocessing.preprocessing_main import preproccessing
from cea.optimization.lca_calculations import lca_calculations
import cea.technologies.solar.solar_collector as solar_collector

__author__ = "Jimeno A. Fonseca"
__copyright__ = "Copyright 2016, Architecture and Building Systems - ETH Zurich"
__credits__ = ["Thuy-an Ngugen", "Jimeno A. Fonseca"]
__license__ = "MIT"
__version__ = "0.1"
__maintainer__ = "Daren Thomas"
__email__ = "thomas@arch.ethz.ch"
__status__ = "Production"


# optimization

def moo_optimization(locator, weather_file, gv, config):
    '''
    This function optimizes the conversion, storage and distribution systems of a heating distribution for the case study.
    It requires that solar technologies be calculated in advance and nodes of a distribution should have been already generated.

    :param locator: path to input locator
    :param weather_file: path to weather file
    :param gv: global variables class
    :type locator: string
    :type weather_file: string
    :type gv: class

    :returns: None
    :rtype: Nonetype
    '''

    # read total demand file and names and number of all buildings
    total_demand = pd.read_csv(locator.get_total_demand())
    building_names = total_demand.Name.values
    gv.num_tot_buildings = total_demand.Name.count()
    lca = lca_calculations(locator, config)
    prices = Prices(locator, config)

    # pre-process information regarding resources and technologies (they are treated before the optimization)
    # optimize best systems for every individual building (they will compete against a district distribution solution)
    print "PRE-PROCESSING"
    extra_costs, extra_CO2, extra_primary_energy, solarFeat = preproccessing(locator, total_demand, building_names,
                                                                             weather_file, gv, config,
                                                                             prices, lca)

    # optimize the distribution and linearize the results(at the moment, there is only a linearization of values in Zug)
    print "NETWORK OPTIMIZATION"
    network_features = network_opt.network_opt_main(config, locator)

    # optimize conversion systems
    print "CONVERSION AND STORAGE OPTIMIZATION"
    master.evolutionary_algo_main(locator, building_names, extra_costs, extra_CO2, extra_primary_energy, solarFeat,
                                  network_features, gv, config, prices, lca)


# ============================
# test
# ============================


def main(config):
    """
    run the whole optimization routine
    """
    gv = cea.globalvar.GlobalVariables()
    locator = cea.inputlocator.InputLocator(scenario=config.scenario)
    weather_file = config.weather

    try:
        if not demand_files_exist(config, locator):
            raise ValueError("Missing demand data of the scenario. Consider running demand script first")

        if not os.path.exists(locator.get_total_demand()):
            raise ValueError("Missing total demand of the scenario. Consider running demand script first")

        if not os.path.exists(locator.PV_totals()):
            raise ValueError("Missing PV potential of the scenario. Consider running photovoltaic script first")

        if config.optimization.isheating:
            if not os.path.exists(locator.PVT_totals()):
                raise ValueError("Missing PVT potential of the scenario. Consider running photovoltaic-thermal script first")

        if not os.path.exists(locator.SC_totals(panel_type = 'FP')):
            raise ValueError(
                "Missing SC potential of panel type 'FP' of the scenario. Consider running solar-collector script first with panel_type as SC1 and t-in-SC as 75")

        if not os.path.exists(locator.SC_totals(panel_type = 'ET')):
            raise ValueError(
                "Missing SC potential of panel type 'ET' of the scenario. Consider running solar-collector script first with panel_type as SC2 and t-in-SC as 150")

        if not os.path.exists(locator.get_sewage_heat_potential()):
            raise ValueError("Missing sewage potential of the scenario. Consider running sewage heat exchanger script first")

        if not os.path.exists(locator.get_lake_potential()):
            raise ValueError("Missing lake potential of the scenario. Consider running lake potential script first")

        if not os.path.exists(locator.get_optimization_network_edge_list_file(config.thermal_network.network_type, '')):
            raise ValueError("Missing network edge list. Consider running thermal network script first")
    except ValueError as err:
        import sys
        print(err.message)
        sys.exit(1)

    print (config.optimization.initialind)
    moo_optimization(locator=locator, weather_file=weather_file, gv=gv, config=config)

    print 'test_optimization_main() succeeded'

def demand_files_exist(config, locator):
    # verify that the necessary demand files exist
    return all(os.path.exists(locator.get_demand_results_file(building_name)) for building_name in locator.get_zone_building_names())

if __name__ == '__main__':
    main(cea.config.Configuration())
