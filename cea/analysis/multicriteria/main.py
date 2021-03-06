"""
Multi criteria decision analysis
"""
from __future__ import division
from __future__ import print_function

import json
import os

import pandas as pd
import numpy as np
import cea.config
import cea.inputlocator
from cea.optimization.lca_calculations import lca_calculations
from cea.analysis.multicriteria.optimization_post_processing.electricity_imports_exports_script import electricity_import_and_exports
from cea.technologies.solar.photovoltaic import calc_Cinv_pv
from cea.optimization.constants import PUMP_ETA
from cea.constants import DENSITY_OF_WATER_AT_60_DEGREES_KGPERM3
from cea.optimization.constants import SIZING_MARGIN
from cea.analysis.multicriteria.optimization_post_processing.individual_configuration import calc_opex_PV
from cea.technologies.chiller_vapor_compression import calc_Cinv_VCC
from cea.technologies.chiller_absorption import calc_Cinv
from cea.technologies.cooling_tower import calc_Cinv_CT
import cea.optimization.distribution.network_opt_main as network_opt
from cea.analysis.multicriteria.optimization_post_processing.locating_individuals_in_generation_script import locating_individuals_in_generation_script

from math import ceil, log


__author__ = "Sreepathi Bhargava Krishna"
__copyright__ = "Copyright 2018, Architecture and Building Systems - ETH Zurich"
__credits__ = ["Sreepathi Bhargava Krishna"]
__license__ = "MIT"
__version__ = "0.1"
__maintainer__ = "Daren Thomas"
__email__ = "cea@arch.ethz.ch"
__status__ = "Production"


def multi_criteria_main(locator, config):
    # local variables
    generation = config.multi_criteria.generations
    category = "optimization-detailed"
    if not os.path.exists(locator.get_address_of_individuals_of_a_generation(generation, category)):
        data_address = locating_individuals_in_generation_script(generation, locator)
    else:
        data_address = pd.read_csv(locator.get_address_of_individuals_of_a_generation(generation, category))

    # initialize class
    data_generation = preprocessing_generations_data(locator, generation)
    objectives = data_generation['final_generation']['population']
    individual_list = objectives.axes[0].values
    data_processed = preprocessing_cost_data(locator, data_generation['final_generation'], individual_list[0], generation, data_address, config)
    column_names = data_processed.columns.values

    compiled_data = pd.DataFrame(np.zeros([len(individual_list), len(column_names)]), columns=column_names)

    for i, individual in enumerate(individual_list):
        data_processed = preprocessing_cost_data(locator, data_generation['final_generation'], individual, generation, data_address, config)
        for name in column_names:
            compiled_data.loc[i][name] = data_processed[name][0]

    compiled_data = compiled_data.assign(individual=individual_list)

    normalized_TAC = (compiled_data['TAC_Mio'] - min(compiled_data['TAC_Mio'])) / (
                max(compiled_data['TAC_Mio']) - min(compiled_data['TAC_Mio']))
    normalized_emissions = (compiled_data['emissions_kiloton'] - min(compiled_data['emissions_kiloton'])) / (
                max(compiled_data['emissions_kiloton']) - min(compiled_data['emissions_kiloton']))
    normalized_prim = (compiled_data['prim_energy_TJ'] - min(compiled_data['prim_energy_TJ'])) / (
                max(compiled_data['prim_energy_TJ']) - min(compiled_data['prim_energy_TJ']))
    normalized_Capex_total = (compiled_data['Capex_total_Mio'] - min(compiled_data['Capex_total_Mio'])) / (
                max(compiled_data['Capex_total_Mio']) - min(compiled_data['Capex_total_Mio']))
    normalized_Opex = (compiled_data['Opex_total_Mio'] - min(compiled_data['Opex_total_Mio'])) / (
                max(compiled_data['Opex_total_Mio']) - min(compiled_data['Opex_total_Mio']))
    normalized_renewable_share = (compiled_data['renewable_share_electricity'] - min(compiled_data['renewable_share_electricity'])) / (
                max(compiled_data['renewable_share_electricity']) - min(compiled_data['renewable_share_electricity']))

    compiled_data = compiled_data.assign(normalized_TAC=normalized_TAC)
    compiled_data = compiled_data.assign(normalized_emissions=normalized_emissions)
    compiled_data = compiled_data.assign(normalized_prim=normalized_prim)
    compiled_data = compiled_data.assign(normalized_Capex_total=normalized_Capex_total)
    compiled_data = compiled_data.assign(normalized_Opex=normalized_Opex)
    compiled_data = compiled_data.assign(normalized_renewable_share=normalized_renewable_share)

    compiled_data['TAC_rank'] = compiled_data['normalized_TAC'].rank(ascending=True)
    compiled_data['emissions_rank'] = compiled_data['normalized_emissions'].rank(ascending=True)
    compiled_data['prim_rank'] = compiled_data['normalized_prim'].rank(ascending=True)

    # user defined mcda
    compiled_data['user_MCDA'] = compiled_data['normalized_Capex_total'] * config.multi_criteria.capextotal * config.multi_criteria.economicsustainability + \
                                 compiled_data['normalized_Opex'] * config.multi_criteria.opex * config.multi_criteria.economicsustainability + \
                                 compiled_data['normalized_TAC'] * config.multi_criteria.annualizedcosts * config.multi_criteria.economicsustainability + \
                                 compiled_data['normalized_emissions'] *config.multi_criteria.emissions * config.multi_criteria.environmentalsustainability + \
                                 compiled_data['normalized_prim'] *config.multi_criteria.primaryenergy * config.multi_criteria.environmentalsustainability + \
                                 compiled_data['normalized_renewable_share'] * config.multi_criteria.renewableshare * config.multi_criteria.socialsustainability

    compiled_data['user_MCDA_rank'] = compiled_data['user_MCDA'].rank(ascending=True)

    compiled_data.to_csv(locator.get_multi_criteria_analysis(generation))

    return compiled_data


def preprocessing_generations_data(locator, generations):

    data_processed = []
    with open(locator.get_optimization_checkpoint(generations), "rb") as fp:
        data = json.load(fp)
    # get lists of data for performance values of the population
    costs_Mio = [round(objectives[0] / 1000000, 2) for objectives in
                 data['population_fitness']]  # convert to millions
    emissions_kiloton = [round(objectives[1] / 1000000, 2) for objectives in
                     data['population_fitness']]  # convert to tons x 10^3 (kiloton)
    prim_energy_TJ = [round(objectives[2] / 1000000, 2) for objectives in
                      data['population_fitness']]  # convert to gigajoules x 10^3 (Terajoules)
    individual_names = ['ind' + str(i) for i in range(len(costs_Mio))]

    df_population = pd.DataFrame({'Name': individual_names, 'costs_Mio': costs_Mio,
                                  'emissions_kiloton': emissions_kiloton, 'prim_energy_TJ': prim_energy_TJ
                                  }).set_index("Name")

    individual_barcode = [[str(ind) if type(ind) == float else str(ind) for ind in
                           individual] for individual in data['population']]
    def_individual_barcode = pd.DataFrame({'Name': individual_names,
                                           'individual_barcode': individual_barcode}).set_index("Name")

    # get lists of data for performance values of the population (hall_of_fame
    costs_Mio_HOF = [round(objectives[0] / 1000000, 2) for objectives in
                     data['halloffame_fitness']]  # convert to millions
    emissions_kiloton_HOF = [round(objectives[1] / 1000000, 2) for objectives in
                         data['halloffame_fitness']]  # convert to tons x 10^3
    prim_energy_TJ_HOF = [round(objectives[2] / 1000000, 2) for objectives in
                          data['halloffame_fitness']]  # convert to gigajoules x 10^3
    individual_names_HOF = ['ind' + str(i) for i in range(len(costs_Mio_HOF))]
    df_halloffame = pd.DataFrame({'Name': individual_names_HOF, 'costs_Mio': costs_Mio_HOF,
                                  'emissions_kiloton': emissions_kiloton_HOF,
                                  'prim_energy_TJ': prim_energy_TJ_HOF}).set_index("Name")

    # get dataframe with capacity installed per individual
    for i, individual in enumerate(individual_names):
        dict_capacities = data['capacities'][i]
        dict_network = data['disconnected_capacities'][i]["network"]
        list_dict_disc_capacities = data['disconnected_capacities'][i]["disconnected_capacity"]
        for building, dict_disconnected in enumerate(list_dict_disc_capacities):
            if building == 0:
                df_disc_capacities = pd.DataFrame(dict_disconnected, index=[dict_disconnected['building_name']])
            else:
                df_disc_capacities = df_disc_capacities.append(
                    pd.DataFrame(dict_disconnected, index=[dict_disconnected['building_name']]))
        df_disc_capacities = df_disc_capacities.set_index('building_name')
        dict_disc_capacities = df_disc_capacities.sum(axis=0).to_dict()  # series with sum of capacities

        if i == 0:
            df_disc_capacities_final = pd.DataFrame(dict_disc_capacities, index=[individual])
            df_capacities = pd.DataFrame(dict_capacities, index=[individual])
            df_network = pd.DataFrame({"network": dict_network}, index=[individual])
        else:
            df_capacities = df_capacities.append(pd.DataFrame(dict_capacities, index=[individual]))
            df_network = df_network.append(pd.DataFrame({"network": dict_network}, index=[individual]))
            df_disc_capacities_final = df_disc_capacities_final.append(
                pd.DataFrame(dict_disc_capacities, index=[individual]))

    data_processed.append(
        {'population': df_population, 'halloffame': df_halloffame, 'capacities_W': df_capacities,
         'disconnected_capacities_W': df_disc_capacities_final, 'network': df_network,
         'spread': data['spread'], 'euclidean_distance': data['euclidean_distance'],
         'individual_barcode': def_individual_barcode})

    return {'all_generations': data_processed, 'final_generation': data_processed[-1:][0]}

def preprocessing_cost_data(locator, data_raw, individual, generations, data_address, config):

    string_network = data_raw['network'].loc[individual].values[0]
    total_demand = pd.read_csv(locator.get_total_demand())
    building_names = total_demand.Name.values
    individual_barcode_list = data_raw['individual_barcode'].loc[individual].values[0]

    # The current structure of CEA has the following columns saved, in future, this will be slightly changed and
    # correspondingly these columns_of_saved_files needs to be changed
    columns_of_saved_files = ['CHP/Furnace', 'CHP/Furnace Share', 'Base Boiler',
                              'Base Boiler Share', 'Peak Boiler', 'Peak Boiler Share',
                              'Heating Lake', 'Heating Lake Share', 'Heating Sewage', 'Heating Sewage Share', 'GHP',
                              'GHP Share',
                              'Data Centre', 'Compressed Air', 'PV', 'PV Area Share', 'PVT', 'PVT Area Share', 'SC_ET',
                              'SC_ET Area Share', 'SC_FP', 'SC_FP Area Share', 'DHN Temperature', 'DHN unit configuration',
                              'Lake Cooling', 'Lake Cooling Share', 'VCC Cooling', 'VCC Cooling Share',
                              'Absorption Chiller', 'Absorption Chiller Share', 'Storage', 'Storage Share',
                              'DCN Temperature', 'DCN unit configuration']
    for i in building_names:  # DHN
        columns_of_saved_files.append(str(i) + ' DHN')

    for i in building_names:  # DCN
        columns_of_saved_files.append(str(i) + ' DCN')

    df_current_individual = pd.DataFrame(np.zeros(shape = (1, len(columns_of_saved_files))), columns=columns_of_saved_files)
    for i, ind in enumerate((columns_of_saved_files)):
        df_current_individual[ind] = individual_barcode_list[i]

    data_address = data_address[data_address['individual_list'] == individual]

    generation_number = data_address['generation_number_address'].values[0]
    individual_number = data_address['individual_number_address'].values[0]
    # get data about the activation patterns of these buildings (main units)

    if config.multi_criteria.network_type == 'DH':
        building_demands_df = pd.read_csv(locator.get_optimization_network_results_summary(string_network)).set_index(
            "DATE")
        data_activation_path = os.path.join(
            locator.get_optimization_slave_heating_activation_pattern(individual_number, generation_number))
        df_heating = pd.read_csv(data_activation_path).set_index("DATE")

        data_activation_path = os.path.join(
            locator.get_optimization_slave_electricity_activation_pattern_heating(individual_number, generation_number))
        df_electricity = pd.read_csv(data_activation_path).set_index("DATE")

        # get data about the activation patterns of these buildings (storage)
        data_storage_path = os.path.join(
            locator.get_optimization_slave_storage_operation_data(individual_number, generation_number))
        df_SO = pd.read_csv(data_storage_path).set_index("DATE")

        # join into one database
        data_processed = df_heating.join(df_electricity).join(df_SO).join(building_demands_df)

    elif config.multi_criteria.network_type == 'DC':

        data_costs = pd.read_csv(os.path.join(locator.get_optimization_slave_investment_cost_detailed_cooling(individual_number, generation_number)))
        data_cooling = pd.read_csv(os.path.join(locator.get_optimization_slave_cooling_activation_pattern(individual_number, generation_number)))
        data_electricity = pd.read_csv(os.path.join(locator.get_optimization_slave_electricity_activation_pattern_cooling(individual_number, generation_number)))

        # Total CAPEX calculations
        # Absorption Chiller
        Absorption_chiller_cost_data = pd.read_excel(locator.get_supply_systems(config.region), sheetname="Absorption_chiller",
                                  usecols=['type', 'code', 'cap_min', 'cap_max', 'a', 'b', 'c', 'd', 'e', 'IR_%',
                                           'LT_yr', 'O&M_%'])
        Absorption_chiller_cost_data = Absorption_chiller_cost_data[Absorption_chiller_cost_data['type'] == 'double']
        max_ACH_chiller_size = max(Absorption_chiller_cost_data['cap_max'].values)
        Inv_IR = (Absorption_chiller_cost_data.iloc[0]['IR_%']) / 100
        Inv_LT = Absorption_chiller_cost_data.iloc[0]['LT_yr']
        Q_ACH_max_W = data_cooling['Q_from_ACH_W'].max()
        Q_ACH_max_W = Q_ACH_max_W * (1 + SIZING_MARGIN)
        number_of_ACH_chillers = max(int(ceil(Q_ACH_max_W / max_ACH_chiller_size)) , 1)
        Q_nom_ACH_W = Q_ACH_max_W / number_of_ACH_chillers
        Capex_a_ACH, Opex_fixed_ACH = calc_Cinv(Q_nom_ACH_W, locator, 'double', config)
        Capex_total_ACH = (Capex_a_ACH * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT) * number_of_ACH_chillers
        data_costs['Capex_total_ACH'] = Capex_total_ACH
        data_costs['Opex_total_ACH'] = np.sum(data_cooling['Opex_var_ACH']) + data_costs['Opex_fixed_ACH']

        # VCC
        VCC_cost_data = pd.read_excel(locator.get_supply_systems(config.region), sheetname="Chiller")
        VCC_cost_data = VCC_cost_data[VCC_cost_data['code'] == 'CH3']
        max_VCC_chiller_size = max(VCC_cost_data['cap_max'].values)
        Inv_IR = (VCC_cost_data.iloc[0]['IR_%']) / 100
        Inv_LT = VCC_cost_data.iloc[0]['LT_yr']
        Q_VCC_max_W = data_cooling['Q_from_VCC_W'].max()
        Q_VCC_max_W = Q_VCC_max_W * (1 + SIZING_MARGIN)
        number_of_VCC_chillers = max(int(ceil(Q_VCC_max_W / max_VCC_chiller_size)), 1)
        Q_nom_VCC_W = Q_VCC_max_W / number_of_VCC_chillers
        Capex_a_VCC, Opex_fixed_VCC = calc_Cinv_VCC(Q_nom_VCC_W, locator, config, 'CH3')
        Capex_total_VCC = (Capex_a_VCC * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT) * number_of_VCC_chillers
        data_costs['Capex_total_VCC'] = Capex_total_VCC
        data_costs['Opex_total_VCC'] = np.sum(data_cooling['Opex_var_VCC']) + data_costs['Opex_fixed_VCC']

        # VCC Backup
        Q_VCC_backup_max_W = data_cooling['Q_from_VCC_backup_W'].max()
        Q_VCC_backup_max_W = Q_VCC_backup_max_W * (1 + SIZING_MARGIN)
        number_of_VCC_backup_chillers = max(int(ceil(Q_VCC_backup_max_W / max_VCC_chiller_size)), 1)
        Q_nom_VCC_backup_W = Q_VCC_backup_max_W / number_of_VCC_backup_chillers
        Capex_a_VCC_backup, Opex_fixed_VCC_backup = calc_Cinv_VCC(Q_nom_VCC_backup_W, locator, config, 'CH3')
        Capex_total_VCC_backup = (Capex_a_VCC_backup * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT) * number_of_VCC_backup_chillers
        data_costs['Capex_total_VCC_backup'] = Capex_total_VCC_backup
        data_costs['Opex_total_VCC_backup'] = np.sum(data_cooling['Opex_var_VCC_backup']) + data_costs['Opex_fixed_VCC_backup']

        # Storage Tank
        storage_cost_data = pd.read_excel(locator.get_supply_systems(config.region), sheetname="TES")
        storage_cost_data = storage_cost_data[storage_cost_data['code'] == 'TES2']
        Inv_IR = (storage_cost_data.iloc[0]['IR_%']) / 100
        Inv_LT = storage_cost_data.iloc[0]['LT_yr']
        Capex_a_storage_tank = data_costs['Capex_a_Tank'][0]
        Capex_total_storage_tank = (Capex_a_storage_tank * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT)
        data_costs['Capex_total_storage_tank'] = Capex_total_storage_tank
        data_costs['Opex_total_storage_tank'] = np.sum(data_cooling['Opex_var_VCC_backup']) + data_costs['Opex_fixed_Tank']

        # Cooling Tower
        CT_cost_data = pd.read_excel(locator.get_supply_systems(config.region), sheetname="CT")
        CT_cost_data = CT_cost_data[CT_cost_data['code'] == 'CT1']
        max_CT_size = max(CT_cost_data['cap_max'].values)
        Inv_IR = (CT_cost_data.iloc[0]['IR_%']) / 100
        Inv_LT = CT_cost_data.iloc[0]['LT_yr']
        Qc_CT_max_W = data_cooling['Qc_CT_associated_with_all_chillers_W'].max()
        number_of_CT = max(int(ceil(Qc_CT_max_W / max_CT_size)), 1)
        Qnom_CT_W = Qc_CT_max_W/number_of_CT
        Capex_a_CT, Opex_fixed_CT = calc_Cinv_CT(Qnom_CT_W, locator, config, 'CT1')
        Capex_total_CT = (Capex_a_CT * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT) * number_of_CT
        data_costs['Capex_total_CT'] = Capex_total_CT
        data_costs['Opex_total_CT'] = np.sum(data_cooling['Opex_var_CT']) + data_costs['Opex_fixed_CT']

        # CCGT
        CCGT_cost_data = pd.read_excel(locator.get_supply_systems(config.region), sheetname="CCGT")
        technology_code = list(set(CCGT_cost_data['code']))
        CCGT_cost_data = CCGT_cost_data[CCGT_cost_data['code'] == technology_code[0]]
        Inv_IR = (CCGT_cost_data.iloc[0]['IR_%']) / 100
        Inv_LT = CCGT_cost_data.iloc[0]['LT_yr']
        Capex_a_CCGT = data_costs['Capex_a_CCGT'][0]
        Capex_total_CCGT = (Capex_a_CCGT * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT)
        data_costs['Capex_total_CCGT'] = Capex_total_CCGT
        data_costs['Opex_total_CCGT'] = np.sum(data_cooling['Opex_var_CCGT']) + data_costs['Opex_fixed_CCGT']

        # pump
        config.restricted_to = None  # FIXME: remove this later
        config.thermal_network.network_type = config.multi_criteria.network_type
        config.thermal_network.network_names = []
        network_features = network_opt.network_opt_main(config, locator)
        DCN_barcode = ""
        for name in building_names:
            DCN_barcode += str(df_current_individual[name + ' DCN'][0])
        if df_current_individual['Data Centre'][0] == 1:
            df = pd.read_csv(locator.get_optimization_network_data_folder("Network_summary_result_" + hex(int(str(DCN_barcode), 2)) + ".csv"),
                             usecols=["mdot_cool_space_cooling_and_refrigeration_netw_all_kgpers"])
        else:
            df = pd.read_csv(locator.get_optimization_network_data_folder("Network_summary_result_" + hex(int(str(DCN_barcode), 2)) + ".csv"),
                             usecols=["mdot_cool_space_cooling_data_center_and_refrigeration_netw_all_kgpers"])
        mdotA_kgpers = np.array(df)
        mdotnMax_kgpers = np.amax(mdotA_kgpers)
        deltaPmax = np.max((network_features.DeltaP_DCN) * DCN_barcode.count("1") / len(DCN_barcode))
        E_pumping_required_W = mdotnMax_kgpers * deltaPmax / DENSITY_OF_WATER_AT_60_DEGREES_KGPERM3
        P_motor_tot_W = E_pumping_required_W / PUMP_ETA  # electricty to run the motor
        Pump_max_kW = 375.0
        Pump_min_kW = 0.5
        nPumps = int(np.ceil(P_motor_tot_W / 1000.0 / Pump_max_kW))
        # if the nominal load (electric) > 375kW, a new pump is installed
        Pump_Array_W = np.zeros((nPumps))
        Pump_Remain_W = P_motor_tot_W
        Capex_total_pumps = 0
        Capex_a_total_pumps = 0
        for pump_i in range(nPumps):
            # calculate pump nominal capacity
            Pump_Array_W[pump_i] = min(Pump_Remain_W, Pump_max_kW * 1000)
            if Pump_Array_W[pump_i] < Pump_min_kW * 1000:
                Pump_Array_W[pump_i] = Pump_min_kW * 1000
            Pump_Remain_W -= Pump_Array_W[pump_i]
            pump_cost_data = pd.read_excel(locator.get_supply_systems(config.region), sheetname="Pump")
            pump_cost_data = pump_cost_data[pump_cost_data['code'] == 'PU1']
            # if the Q_design is below the lowest capacity available for the technology, then it is replaced by the least
            # capacity for the corresponding technology from the database
            if Pump_Array_W[pump_i] < pump_cost_data.iloc[0]['cap_min']:
                Pump_Array_W[pump_i] = pump_cost_data.iloc[0]['cap_min']
            pump_cost_data = pump_cost_data[
                (pump_cost_data['cap_min'] <= Pump_Array_W[pump_i]) & (
                            pump_cost_data['cap_max'] > Pump_Array_W[pump_i])]
            Inv_a = pump_cost_data.iloc[0]['a']
            Inv_b = pump_cost_data.iloc[0]['b']
            Inv_c = pump_cost_data.iloc[0]['c']
            Inv_d = pump_cost_data.iloc[0]['d']
            Inv_e = pump_cost_data.iloc[0]['e']
            Inv_IR = (pump_cost_data.iloc[0]['IR_%']) / 100
            Inv_LT = pump_cost_data.iloc[0]['LT_yr']
            Inv_OM = pump_cost_data.iloc[0]['O&M_%'] / 100
            InvC = Inv_a + Inv_b * (Pump_Array_W[pump_i]) ** Inv_c + (Inv_d + Inv_e * Pump_Array_W[pump_i]) * log(
                Pump_Array_W[pump_i])
            Capex_total_pumps += InvC
            Capex_a_total_pumps += InvC * (Inv_IR) * (1 + Inv_IR) ** Inv_LT / ((1 + Inv_IR) ** Inv_LT - 1)
        data_costs['Capex_total_pumps'] = Capex_total_pumps
        data_costs['Opex_total_pumps'] = data_costs['Opex_fixed_pump'] + data_costs['Opex_fixed_pump']

        # PV
        pv_installed_area = data_electricity['Area_PV_m2'].max()
        Capex_a_PV, Opex_fixed_PV = calc_Cinv_pv(pv_installed_area, locator, config)
        pv_annual_production_kWh = (data_electricity['E_PV_W'].sum()) / 1000
        Opex_a_PV = calc_opex_PV(pv_annual_production_kWh, pv_installed_area)
        PV_cost_data = pd.read_excel(locator.get_supply_systems(config.region), sheetname="PV")
        technology_code = list(set(PV_cost_data['code']))
        PV_cost_data[PV_cost_data['code'] == technology_code[0]]
        Inv_IR = (PV_cost_data.iloc[0]['IR_%']) / 100
        Inv_LT = PV_cost_data.iloc[0]['LT_yr']
        Capex_total_PV = (Capex_a_PV * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT)
        data_costs['Capex_total_PV'] = Capex_total_PV
        data_costs['Opex_total_PV'] = Opex_a_PV + Opex_fixed_PV

        # Disconnected Buildings
        Capex_total_disconnected = 0
        Opex_total_disconnected = 0
        Capex_a_total_disconnected = 0

        for (index, building_name) in zip(DCN_barcode, building_names):
            if index is '0':
                df = pd.read_csv(locator.get_optimization_disconnected_folder_building_result_cooling(building_name,
                                                                                                      configuration='AHU_ARU_SCU'))
                dfBest = df[df["Best configuration"] == 1]

                if dfBest['VCC to AHU_ARU_SCU Share'].iloc[0] == 1: #FIXME: Check for other options
                    Inv_IR = (VCC_cost_data.iloc[0]['IR_%']) / 100
                    Inv_LT = VCC_cost_data.iloc[0]['LT_yr']

                if dfBest['single effect ACH to AHU_ARU_SCU Share (FP)'].iloc[0] == 1:
                    Inv_IR = (Absorption_chiller_cost_data.iloc[0]['IR_%']) / 100
                    Inv_LT = Absorption_chiller_cost_data.iloc[0]['LT_yr']

                Opex_total_disconnected += dfBest["Operation Costs [CHF]"].iloc[0]
                Capex_a_total_disconnected += dfBest["Annualized Investment Costs [CHF]"].iloc[0]
                Capex_total_disconnected += (dfBest["Annualized Investment Costs [CHF]"].iloc[0] * ((1 + Inv_IR) ** Inv_LT - 1) / (Inv_IR) * (1 + Inv_IR) ** Inv_LT)
        data_costs['Capex_total_disconnected_Mio'] = Capex_total_disconnected / 1000000
        data_costs['Opex_total_disconnected_Mio'] = Opex_total_disconnected / 1000000
        data_costs['Capex_a_disconnected_Mio'] = Capex_a_total_disconnected / 1000000

        data_costs['costs_Mio'] = data_raw['population']['costs_Mio'][individual]
        data_costs['emissions_kiloton'] = data_raw['population']['emissions_kiloton'][individual]
        data_costs['prim_energy_TJ'] = data_raw['population']['prim_energy_TJ'][individual]

        # Electricity Details/Renewable Share
        total_electricity_demand_decentralized_W = np.zeros(8760)

        DCN_barcode = ""
        for name in building_names:  # identifying the DCN code
            DCN_barcode += str(int(df_current_individual[name + ' DCN'].values[0]))
        for i, name in zip(DCN_barcode,
                           building_names):  # adding the electricity demand from the decentralized buildings
            if i is '0':
                building_demand = pd.read_csv(locator.get_demand_results_folder() + '//' + name + ".csv",
                                              usecols=['E_sys_kWh'])

                total_electricity_demand_decentralized_W += building_demand['E_sys_kWh'] * 1000

        lca = lca_calculations(locator, config)

        data_electricity_processed = electricity_import_and_exports(generation_number, individual_number, locator, config)

        data_costs['Network_electricity_demand_GW'] = (data_electricity['E_total_req_W'].sum()) / 1000000000 # GW
        data_costs['Decentralized_electricity_demand_GW'] = (data_electricity_processed['E_decentralized_appliances_W'].sum()) / 1000000000 # GW
        data_costs['Total_electricity_demand_GW'] = (data_electricity_processed['E_total_req_W'].sum()) / 1000000000 # GW

        renewable_share_electricity = (data_electricity_processed['E_PV_to_directload_W'].sum() +
                                       data_electricity_processed['E_PV_to_grid_W'].sum()) * 100 / \
                                      (data_costs['Total_electricity_demand_GW'] * 1000000000)
        data_costs['renewable_share_electricity'] = renewable_share_electricity

        data_costs['Electricity_Costs_Mio'] = ((data_electricity_processed['E_from_grid_W'].sum() +
                                           data_electricity_processed[
                                               'E_total_to_grid_W_negative'].sum()) * lca.ELEC_PRICE) / 1000000

        data_costs['Capex_a_total_Mio'] = (Capex_a_ACH * number_of_ACH_chillers + Capex_a_VCC * number_of_VCC_chillers + \
                    Capex_a_VCC_backup * number_of_VCC_backup_chillers + Capex_a_CT * number_of_CT + Capex_a_storage_tank + \
                    Capex_a_total_pumps + Capex_a_CCGT + Capex_a_PV + Capex_a_total_disconnected) / 1000000

        data_costs['Capex_a_ACH'] = Capex_a_ACH * number_of_ACH_chillers
        data_costs['Capex_a_VCC'] = Capex_a_VCC * number_of_VCC_chillers
        data_costs['Capex_a_VCC_backup'] = Capex_a_VCC_backup * number_of_VCC_backup_chillers
        data_costs['Capex_a_CT'] = Capex_a_CT * number_of_CT
        data_costs['Capex_a_storage_tank'] = Capex_a_storage_tank
        data_costs['Capex_a_total_pumps'] = Capex_a_total_pumps
        data_costs['Capex_a_CCGT'] = Capex_a_CCGT
        data_costs['Capex_a_PV'] = Capex_a_PV

        data_costs['Capex_total_Mio'] = (data_costs['Capex_total_ACH'] + data_costs['Capex_total_VCC'] + data_costs['Capex_total_VCC_backup'] + \
                                    data_costs['Capex_total_storage_tank'] + data_costs['Capex_total_CT'] + data_costs['Capex_total_CCGT'] + \
                                    data_costs['Capex_total_pumps'] + data_costs['Capex_total_PV'] + Capex_total_disconnected) / 1000000

        data_costs['Opex_total_Mio'] = ((data_costs['Opex_total_ACH'] + data_costs['Opex_total_VCC'] + data_costs['Opex_total_VCC_backup'] + \
                                   data_costs['Opex_total_storage_tank'] + data_costs['Opex_total_CT'] + data_costs['Opex_total_CCGT'] + \
                                   data_costs['Opex_total_pumps'] + Opex_total_disconnected) / 1000000) + data_costs['Electricity_Costs_Mio']

        data_costs['TAC_Mio'] = data_costs['Capex_a_total_Mio'] + data_costs['Opex_total_Mio']

    return data_costs

def main(config):
    locator = cea.inputlocator.InputLocator(config.scenario)

    print("Running dashboard with scenario = %s" % config.scenario)
    print("Running dashboard with the next generations = %s" % config.multi_criteria.generations)

    multi_criteria_main(locator, config)


if __name__ == '__main__':
    main(cea.config.Configuration())