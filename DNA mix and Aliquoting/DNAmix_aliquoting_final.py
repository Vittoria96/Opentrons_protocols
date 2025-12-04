from opentrons import protocol_api
from opentrons.protocol_api import SINGLE, ALL

metadata = {
    'protocolName': 'DNA Mix Aliquoting',
    'author': 'dB',
    'description': 'Protocol for automated aliquoting of DNA transfection mix',
}

requirements = {
    'robotType': 'Flex',
    'apiLevel': '2.20'
}


def add_parameters(parameters):
    # List of valid well options (A1–H12)
    well_choices = [{"value": f"{row}{col}", "display_name": f"{row}{col}"}
                    for row in "ABCDEFGH" for col in range(1, 13)]

    # Number of mix wells to prepare
    parameters.add_int(
        display_name="mix count",
        variable_name="mix_count",
        description="Number of different mixes to aliquot",
        default=12,
        minimum=1,
        maximum=96
    )

    # Volume of transfection reagent dispensed per mix well
    parameters.add_int(
        display_name="reagent vol",
        variable_name="reagent_vol",
        description="Volume (µL) of NaCl + PEI to add into each mix well",
        default=88,
        minimum=1,
        maximum=1000
    )

    # Final aliquot volume per cell well
    parameters.add_int(
        display_name="aliquot vol",
        variable_name="aliquot_vol",
        description="Volume (µL) of mix to dispense into each cell well",
        default=20,
        minimum=1,
        maximum=1000
    )

    # Source well for the NaCl + PEI reagent
    parameters.add_str(
        variable_name="reagent_eppendorf",
        display_name="Reagent Position",
        description="Position of the Eppendorf containing NaCl + PEI reagent",
        default="D6",
        choices=well_choices
    )

    # First destination well for mix on PCR plate
    parameters.add_str(
        variable_name="mix_position",
        display_name="Mix Position",
        description="Starting well for mixes on PCR plate",
        default="C1",
        choices=well_choices
    )

    # How many rows of PCR plate will contain mix wells
    parameters.add_int(
        variable_name="mix_rows_count",
        display_name="Number of Rows for Mix",
        description="Number of rows occupied by the mix wells",
        default=2,
        minimum=1,
        maximum=8
    )

    # How many columns per row will be used for mix wells
    parameters.add_int(
        variable_name="mix_columns_per_row",
        display_name="Number of Columns per Row",
        description="Number of columns occupied by each row with mixes",
        default=6,
        minimum=1,
        maximum=12
    )

    # Delay before transfer to cell plate
    parameters.add_int(
        display_name="delay",
        variable_name="delay",
        description="Incubation delay before aliquoting (minutes)",
        default=15,
        minimum=1,
        maximum=100
    )

    # Custom starting tip for 200 µL tips
    parameters.add_str(
        variable_name="starting_tip_200",
        display_name="Starting Tip (200 µL)",
        description="First tip to pick up in the 200 µL tip rack",
        default="A1",
        choices=well_choices
    )

    # Custom starting tip for 1000 µL tips
    parameters.add_str(
        variable_name="starting_tip_1000",
        display_name="Starting Tip (1000 µL)",
        description="First tip to pick up in the 1000 µL tip rack",
        default="A1",
        choices=well_choices
    )

    # Select reagent tube rack type
    parameters.add_str(
        variable_name="reagent_plate_type",
        display_name="Tube Rack Type for Reagent",
        default="opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap",
        choices=[
            {"display_name": "Eppendorf Tube Rack, 2mL", "value": "opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap"},
            {"display_name": "Eppendorf Tube Rack, 1.5mL", "value": "opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap"}
        ]
    )

    parameters.add_bool(
        variable_name="premix",
        display_name="Premix",
        description="Set true if you want to premix NaCl + PEI",
        default = False
    )

    parameters.add_int(
        variable_name="premixvol",
        display_name="Volume for reagent premix",
        description="Volume for mixing NaCl + PEI before distribution",
        default=2,
        minimum=1,
        maximum=900
    )



def run(protocol: protocol_api.ProtocolContext):
    # Load user parameters
    p = protocol.params
    mix_count = p.mix_count
    reagent_vol = p.reagent_vol
    aliquot_vol = p.aliquot_vol
    reagent_eppendorf = p.reagent_eppendorf
    mix_position = p.mix_position
    mix_rows_count = p.mix_rows_count
    mix_columns_per_row = p.mix_columns_per_row
    delay = p.delay
    starting_tip_200 = p.starting_tip_200
    starting_tip_1000 = p.starting_tip_1000
    reagent_plate_type = p.reagent_plate_type
    premixvol = p.premixvol
    premix = p.premix


    # Load labware
    tiprack_1000 = protocol.load_labware('opentrons_flex_96_filtertiprack_1000ul', 'B1',
                                         adapter='opentrons_flex_96_tiprack_adapter')
    tiprack_200 = protocol.load_labware('opentrons_flex_96_filtertiprack_200ul', 'B2',
                                        adapter='opentrons_flex_96_tiprack_adapter')
    heater_shaker = protocol.load_module('heaterShakerModuleV1', 'D1')
    pcr_plate = heater_shaker.load_labware('biorad_96_wellplate_200ul_pcr')
    reagent_plate = protocol.load_labware(reagent_plate_type, 'D3')
    cell_plate = protocol.load_labware('corning_96_wellplate_360ul_flat', 'C3')
    trash = protocol.load_trash_bin('A3')

    # Load single-channel configuration of the Flex 8-channel
    p1000 = protocol.load_instrument('flex_8channel_1000', 'right')
    p1000.configure_nozzle_layout(style=SINGLE, start="H1")  # Single nozzle mode

    # Create linear list of tips by row (A1 → H12)
    tips1000_by_row = sum(tiprack_1000.rows(), [])
    tips200_by_row = sum(tiprack_200.rows(), [])

    # Locating selected starting tip index in rack
    def find_tip_index(tip_list, well_name):
        for i, tip in enumerate(tip_list):
            if tip.well_name == well_name:
                return i
        raise ValueError(f"Starting tip {well_name} not found in tip list.")

    tips200_by_row = tips200_by_row[find_tip_index(tips200_by_row, starting_tip_200):]
    tips1000_by_row = tips1000_by_row[find_tip_index(tips1000_by_row, starting_tip_1000):]

    # Tip usage counters
    counter_1000 = 0
    counter_200 = 0

    # Custom flow rates for gentle handling
    p1000.flow_rate.aspirate = 35
    p1000.flow_rate.dispense = 57

    # Reagent source
    source = reagent_plate[reagent_eppendorf]

    # Determine destination mix wells on PCR plate
    rows = "ABCDEFGH"
    start_row = mix_position[0].upper()
    start_col = int(mix_position[1:])
    row_index = rows.index(start_row)

    # Validate requested geometry
    if row_index + mix_rows_count > len(rows):
        protocol.pause("Error: Too many rows selected for the starting position.")
        raise RuntimeError("Invalid row selection.")

    selected_rows = rows[row_index:row_index + mix_rows_count]
    all_wells = [f"{r}{c}" for r in selected_rows for c in range(start_col, start_col + mix_columns_per_row)]

    if len(all_wells) < mix_count:
        protocol.pause(f"Error: Only {len(all_wells)} wells available for mix placement.")
        raise RuntimeError("Not enough wells assigned for mixes.")

    destination_wells = [pcr_plate[well] for well in all_wells[:mix_count]]

    heater_shaker.close_labware_latch()

    # Pick up tp
    if not p1000.has_tip:
        try:
            p1000.pick_up_tip(tips1000_by_row[counter_1000])
            counter_1000 += 1
        except RuntimeError:
            protocol.pause("Tip pickup failed.")
            raise

    # Volume tracking for efficient reagent transfer
    vol_in_tip = 0
    well_index = 0

    # Distribute reagent across all mix wells
    while well_index < mix_count:
        remaining_wells = mix_count - well_index

        if vol_in_tip < reagent_vol:
            to_aspirate = min(1000 * 0.9, remaining_wells * reagent_vol)  # Maintain safe max volume
            if premix:
                p1000.flow_rate.aspirate = 716
                p1000.flow_rate.dispense = 716
                p1000.mix(3, premixvol, source)  # Pre-mix reagent
                p1000.flow_rate.aspirate = 35
                p1000.flow_rate.dispense = 57
            p1000.aspirate(to_aspirate, source)
            vol_in_tip = to_aspirate

        # Dispense into each mix well
        p1000.dispense(reagent_vol, destination_wells[well_index].top(0))
        p1000.air_gap(5)
        vol_in_tip -= reagent_vol
        well_index += 1

    p1000.drop_tip()

    # Incubation before aliquoting
    protocol.delay(minutes=delay)

    # Aliquot each mix into 4 wells of the cell plate
    for i, source_well in enumerate(destination_wells):
        # Plate layout logic: 6 mixes per block, 4 blocks total
        block = (i // 6) % 4
        col = (i % 6) + 1 + (6 if block in [2, 3] else 0)
        rows_block = ['A', 'B', 'C', 'D'] if block % 2 == 0 else ['E', 'F', 'G', 'H']
        target_locs = [cell_plate[f"{r}{col}"] for r in rows_block]

        # Pick correct tip size based on total aspired volume
        if aliquot_vol * 4 <= 200:
            tip = tips200_by_row[counter_200]
            counter_200 += 1
        else:
            tip = tips1000_by_row[counter_1000]
            counter_1000 += 1

        try:
            p1000.pick_up_tip(tip)
        except RuntimeError:
            protocol.pause("Tip pickup failed.")
            raise

        # Mix at high speed then aspirate & dispense into 4 wells
        p1000.flow_rate.aspirate = p1000.flow_rate.dispense = 716
        p1000.mix(5, reagent_vol, source_well)
        p1000.flow_rate.aspirate = 35
        p1000.flow_rate.dispense = 57

        p1000.aspirate(aliquot_vol * 4, source_well)
        for loc in target_locs:
            p1000.dispense(aliquot_vol, loc)

        p1000.drop_tip()

    # Unlock PCR plate after pipetting
    heater_shaker.open_labware_latch()

    # Tip usage summary
    print('Tips used — 1000 µL:', counter_1000)
    print('Tips used — 200 µL:', counter_200)
