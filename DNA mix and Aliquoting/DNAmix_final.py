from opentrons import protocol_api
from opentrons.protocol_api import SINGLE
import csv
from collections import defaultdict


metadata = {
    'protocolName': 'DNA Mix final',
    'author': 'DdB Opentrons team',
    'description': 'Protocol for DNA mix including NaCl (150mM), handling sub-µL volumes with intermediate mix in Eppendorf tubes',
}

requirements = {
    'robotType': 'Flex',
    'apiLevel': '2.20'
}

def add_parameters(parameters):
    well_choices = [{"value": f"{row}{col}", "display_name": f"{row}{col}"} for row in "ABCDEFGH" for col in range(1, 13)]

    parameters.add_int(
        display_name="Max num of plasmids per mix",
        variable_name="max_plasmid_count",
        description="Maximum number of plasmids in any mix (1-10) including NaCl",
        default=6,
        minimum=1,
        maximum=10
    )

    parameters.add_int(
        display_name="Number of mix",
        variable_name="mix_count",
        description="Number of different mix to create from the CSV data",
        default=3,
        minimum=1,
        maximum=96
    )

    parameters.add_csv_file(
        display_name="Plasmid data CSV",
        variable_name="csv_data",
        description="CSV file containing plasmid volumes, source wells, and destination wells"
    )

    parameters.add_str(
        variable_name="starting_tip_50",
        display_name="Starting tip position (50)",
        description="Starting tip position for 50 µL tips",
        default="A1",
        choices=well_choices
    )

    parameters.add_str(
        variable_name="starting_tip_200",
        display_name="Starting tip (200)",
        description="Starting tip position for 200 µL tips",
        default="A1",
        choices=well_choices
    )

    parameters.add_str(
        variable_name="plasmids_plate_type",
        display_name="Eppendorf volume",
        default="opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap",
        description="Type of Eppendorf",
        choices=[
            {"display_name": "Eppendorf Tube Rack, 2mL",  "value": "opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap"},
            {"display_name": "Eppendorf Tube Rack, 1.5mL", "value": "opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap"}
        ]
    )

    parameters.add_bool(
        display_name="Premix",
        variable_name="premix",
        description="Premix of plasmids",
        default=True
    )

def run(protocol: protocol_api.ProtocolContext):
    # Extract parameters
    max_plasmid_count = protocol.params.max_plasmid_count
    mix_count = protocol.params.mix_count
    batch_size = 12
    starting_tip_50 = protocol.params.starting_tip_50
    starting_tip_200 = protocol.params.starting_tip_200
    plasmids_plate_type = protocol.params.plasmids_plate_type
    premix = protocol.params.premix

    # Load CSV file

    with open("Example.csv", encoding='utf-8-sig', newline='') as f:   # comment this two lines to run on the robot
        csv_data = list(csv.reader(f))


    #csv_data = protocol.params.csv_data.parse_as_csv()                # uncomment this two lines to run on the robot

    # Clean BOM and spaces
    csv_data = [[cell.replace('\ufeff', '').strip() for cell in row] for row in csv_data]

    # Load modules and labware
    heater_shaker = protocol.load_module('heaterShakerModuleV1', 'D1')
    tiprack_50 = protocol.load_labware('opentrons_flex_96_tiprack_50ul', 'B1')
    tiprack_50_reserve = protocol.load_labware('opentrons_flex_96_tiprack_50ul', 'B4')
    tiprack_200 = protocol.load_labware('opentrons_flex_96_tiprack_200ul', 'B2')
    pcr_plate = heater_shaker.load_labware('biorad_96_wellplate_200ul_pcr')
    plasmid_plate = protocol.load_labware(plasmids_plate_type, 'D3')
    trash = protocol.load_trash_bin('A3')

    # Load pipettes
    p1000 = protocol.load_instrument('flex_8channel_1000', 'right', tip_racks=[tiprack_200])
    p1000.configure_nozzle_layout(style=SINGLE, start="H1")
    tips200_by_row = sum(tiprack_200.rows(), [])

    p50 = protocol.load_instrument('flex_8channel_50', 'left', tip_racks=[tiprack_50])
    p50.configure_nozzle_layout(style=SINGLE, start="H1")
    tips50_by_row = sum(tiprack_50.rows(), [])

    # Find starting tip index
    def find_tip_index(tip_list, well_name):
        for i, tip in enumerate(tip_list):
            if tip.well_name == well_name:
                return i
        raise ValueError(f"Starting tip {well_name} not found in tip list.")

    def swap_rack50():
        nonlocal tiprack_50, tiprack_50_reserve, tips50_by_row
        protocol.comment(f"\n====== SWAPPING 50 µL TIP RACK ======")

        protocol.move_labware(tiprack_50, 'C4', use_gripper=True)
        protocol.move_labware(tiprack_50_reserve, 'B1', use_gripper=True)

        tiprack_50, tiprack_50_reserve = tiprack_50_reserve, tiprack_50
        tips50_by_row = sum(tiprack_50.rows(), [])
        counter_50 = 0


    tips50_by_row = tips50_by_row[find_tip_index(tips50_by_row, starting_tip_50):]
    tips200_by_row = tips200_by_row[find_tip_index(tips200_by_row, starting_tip_200):]

    counter_200 = 0
    counter_50 = 0
    counter_50_f = 0

    # --- Define plasmids from CSV ---
    plasmid_name_rows = list(range(0, len(csv_data), 15))  # riga dei nomi ogni 15 righe
    plasmid_well_rows = [row + 13 for row in plasmid_name_rows]

    all_plasmid_wells = {}

    # Parse plasmid names and wells
    for name_row, well_row in zip(plasmid_name_rows, plasmid_well_rows):
        if name_row >= len(csv_data) or well_row >= len(csv_data):
            continue
        plasmid_names = [cell.strip() for cell in csv_data[name_row]]
        for i in range(1, len(plasmid_names)):
            name = plasmid_names[i]
            if not name:
                continue
            well = csv_data[well_row][i].strip() if i < len(csv_data[well_row]) else ""
            if well:
                all_plasmid_wells.setdefault(name, []).append(well)

    # Remove duplicates
    for name in all_plasmid_wells:
        all_plasmid_wells[name] = list(dict.fromkeys(all_plasmid_wells[name]))

    # Register liquids in the deck map
    plasmid_liquids = {}
    plasmid_well_map = {}
    for name, wells in all_plasmid_wells.items():
        liquid = protocol.define_liquid(name=name, description=f"Plasmid {name}", display_color="#3366FF")
        plasmid_liquids[name] = liquid
        for well in wells:
            plasmid_plate[well].load_liquid(liquid, 1000)
            plasmid_well_map[well] = name
        protocol.comment(f"{name} {wells}")

    # --- Define NaCl ---
    nacl_name = "NaCl (150mM)"
    nacl_liquid = protocol.define_liquid(
        name=nacl_name,
        description="NaCl solution 150mM",
        display_color="#FF9933"
    )

    nacl_wells_all = []
    for mix_index in range(mix_count):
        row_index = 13 + 15 * mix_index
        if row_index >= len(csv_data):
            continue
        row = [cell.strip() for cell in csv_data[row_index] if cell.strip()]
        if not row:
            continue
        last_well = row[-1]
        plasmid_plate[last_well].load_liquid(nacl_liquid, 1000)
        plasmid_well_map[last_well] = nacl_name
        nacl_wells_all.append(last_well)
    all_plasmid_wells[nacl_name] = list(dict.fromkeys(nacl_wells_all))
    protocol.comment(f"{nacl_name} {list(dict.fromkeys(nacl_wells_all))}")


    # --- Parse CSV for mixes ---
    all_mix_data = []
    try:
        for mix_index in range(mix_count):
            volume_row_index = 12 + (mix_index * 15)
            source_row_index = volume_row_index + 1
            dest_row_index = 0 + mix_index * 15

            mix_volumes = []
            source_wells = []

            # Main plasmids
            for i in range(1, min(max_plasmid_count + 1, len(csv_data[volume_row_index]))):
                vol_str = csv_data[volume_row_index][i].strip()
                if not vol_str:
                    continue

                vol = float(vol_str)

                if vol < 0:
                    continue

                mix_volumes.append(vol)
                source_wells.append(csv_data[source_row_index][i].strip() or f"A{i + 1}")



            # Rescale if <0.8 µL
            small_volumes = [v for v in mix_volumes if 0 < v < 0.8 ]
            scale_factors = []

            small_volumes_count = sum(1 for v in mix_volumes if 0 < v < 0.8 )


            if small_volumes:
                min_small = min(small_volumes)
                if small_volumes_count > 1:
                    scale_factor = 0.8  /sum(small_volumes)
                else:
                    scale_factor = 0.8  / min_small



                mix_volumes = [v * scale_factor for v in mix_volumes]


                scale_factors.append(scale_factor)

                protocol.comment(f"\nMix {mix_index + 1} had volume < 0.8  µL, volumes have been rescaled")
            else:
                scale_factors = [1] * len(mix_volumes)




            dest_well = csv_data[dest_row_index][0].strip() if csv_data[dest_row_index] else "A1"

            all_mix_data.append({
                'volumes': mix_volumes,
                'scale_factors':scale_factors,
                'source_wells': source_wells,
                'dest_well': dest_well
            })

            volume_info = ", ".join([
                f"{plasmid_well_map.get(well, 'Unknown')} : {vol} µL from {well}"
                for vol, well in zip(mix_volumes, source_wells)
            ])
            protocol.comment(f"\nMix {mix_index + 1} data: {volume_info}")
            protocol.comment(f"Destination well: {dest_well}\n")

    except Exception as e:
        protocol.pause(f"Error parsing CSV: {str(e)}")
        return


    # --- Define intermediate Eppendorf wells ---
    intermediate_small_pool = [f"C{i}" for i in range(1, 7)]
    intermediate_final_pool = [f"D{i}" for i in range(1, 7)]

    intermediate_pool = intermediate_small_pool + intermediate_final_pool

    assigned_small_wells = {}
    assigned_final_wells = {}

    intermediate_liquid = protocol.define_liquid(
        name="Intermediate Mix",
        description="Temporary mix for sub-µL plasmid handling",
        display_color="#99CC00"
    )

    # Assign wells to mixes that contain small volumes

    for mix_data in all_mix_data:
        scale = mix_data['scale_factors'][0]

        small_volumes_count = sum(1 for v in mix_data['volumes'] if 0 < v/scale < 0.8 )


        if small_volumes_count > 1:
            # Serve sia small che final wells
            if not intermediate_small_pool or not intermediate_final_pool:
                protocol.pause("⚠️ Not enough Eppendorf wells available!")
                break

            small_well = intermediate_small_pool.pop(0)
            final_well = intermediate_final_pool.pop(0)

            # Register them as liquids in deck map
            plasmid_plate[small_well].load_liquid(intermediate_liquid, 0)
            plasmid_plate[final_well].load_liquid(intermediate_liquid, 0)

            # Store mapping
            assigned_small_wells[mix_data['dest_well']] = small_well
            assigned_final_wells[mix_data['dest_well']] = final_well

            protocol.comment(f"Intermediate SMALL well for {mix_data['dest_well']}: {small_well}")
            protocol.comment(f"Intermediate FINAL well for {mix_data['dest_well']}: {final_well}")

        elif small_volumes_count == 1:
            # Serve solo final well
            if not intermediate_pool:
                protocol.pause("⚠️ Not enough Eppendorf wells available!")
                break

            final_well = intermediate_pool.pop(0)

            plasmid_plate[final_well].load_liquid(intermediate_liquid, 0)
            assigned_final_wells[mix_data['dest_well']] = final_well

            protocol.comment(f"Intermediate FINAL well for {mix_data['dest_well']}: {final_well}")


    heater_shaker.close_labware_latch()

    # --- Calculate total NaCl for multi-dispensing ---
    nacl_totals = defaultdict(float)  # key = source well name, value = total volume
    nacl_dests = defaultdict(list)    # key = source well name, value = list of destinations

    mix_has_small_volumes = {}

    # Pre-scan mixes to determine which have small plasmid volumes
    for mix_data in all_mix_data:
        mix_has_small_volumes[mix_data['dest_well']] = any(0 < v < 0.8  for v in mix_data['volumes'])


    for mix_data in all_mix_data:
        dest_well_name = mix_data['dest_well']
        nacl_vol = mix_data['volumes'][-1]


        if nacl_vol <= 0:
            continue

        nacl_source_well_name = mix_data['source_wells'][-1]

        if mix_has_small_volumes[dest_well_name]:
            # If small volumes exist, NaCl goes to the final intermediate Eppendorf
            final_epp = assigned_final_wells.get(dest_well_name)
            if final_epp is not None:
                dests = [(plasmid_plate[final_epp], nacl_vol)]
            else:
                # Fallback to PCR plate if Eppendorf not assigned
                dests = [(pcr_plate[dest_well_name], nacl_vol)]
        else:
            # Otherwise, NaCl goes directly to PCR plate
            dests = [(pcr_plate[dest_well_name], nacl_vol)]

        nacl_totals[nacl_source_well_name] += nacl_vol
        nacl_dests[nacl_source_well_name].extend(dests)

    # --- Execute NaCl multi-dispensing ---
    for source_well_name, total_vol in nacl_totals.items():
        dest_list = nacl_dests[source_well_name]
        source = plasmid_plate[source_well_name]
        buffer = 2

        max_vol = 50 if total_vol + buffer <= 50 else 200
        pipette = p50 if max_vol == 50 else p1000

        if pipette == p50:
            if not tips50_by_row:
                swap_rack50()
            pipette.pick_up_tip(location=tips50_by_row.pop(0))
            counter_50 += 1
            counter_50_f += 1
        else:
            pipette.pick_up_tip(location=tips200_by_row.pop(0))
            counter_200 += 1

        group, current_sum = [], 0
        grouped = []

        for dest, vol in dest_list:
            if  current_sum + vol <= max_vol - buffer:
                group.append((dest, vol))
                current_sum += vol
            else:
                grouped.append(group)
                group, current_sum = [(dest, vol)], vol
        if group:
            grouped.append(group)
            for g in grouped:
                total = sum(v for _, v in g)
                pipette.aspirate(total + buffer, source)
                for dest, vol in g:
                    pipette.dispense(vol, dest)
                pipette.blow_out(source.top())

            pipette.drop_tip()

        protocol.comment(
            f"Distributed NaCl from {source_well_name} to: {', '.join([d[0].well_name for d in dest_list])}"
        )


    # --- Execute plasmid transfers ---
    for batch_start in range(0, mix_count, batch_size):
        batch_end = min(batch_start + batch_size, mix_count)
        batch_mix_data = all_mix_data[batch_start:batch_end]

        protocol.comment(f"Processing batch mixes {batch_start + 1} to {batch_end}")

        premixed_sources = set()

        for mix_data in batch_mix_data:
            dest_well = mix_data['dest_well']


            # --- Separate volumes < 0.8 µL ---
            small_volumes = []
            small_sources = []
            normal_volumes = []
            normal_sources = []

            for vol, src in zip(mix_data['volumes'], mix_data['source_wells']):

                plasmid_name = plasmid_well_map.get(src, "Unknown")

                if plasmid_name != "NaCl (150mM)":
                    if premix:
                        if src not in premixed_sources:
                            p1000.pick_up_tip(location=tips200_by_row.pop(0))
                            counter_200 += 1
                            mix_vol = 200
                            mix_reps = 6
                            protocol.comment(f"\nPremix plasmid {plasmid_name} in {src} ({mix_reps}×{mix_vol} µL)")

                            for _ in range(mix_reps):

                                p1000.aspirate(mix_vol, plasmid_plate[src].bottom(1))
                                p1000.dispense(mix_vol, plasmid_plate[src].bottom(10))
                            p1000.blow_out(plasmid_plate[src].top(-2))
                            p1000.drop_tip()
                            premixed_sources.add(src)

            protocol.comment(f"\nTransferring to {dest_well}")

            for vol, src in zip(mix_data['volumes'], mix_data['source_wells']):

                plasmid_name = plasmid_well_map.get(src, "Unknown")
                if plasmid_name == "NaCl (150mM)":
                    continue

                if 0 < vol/ mix_data['scale_factors'][0] < 0.8 :
                    small_volumes.append(vol * 10)
                    small_sources.append(src)
                else:
                    normal_volumes.append(vol)
                    normal_sources.append(src)

            has_small_volumes = len(small_volumes) > 0


            # If small volumes exist, create intermediate mix in Eppendorf tube
            if has_small_volumes:
                if len(small_volumes) > 1:
                    intermediate_well_small = assigned_small_wells[dest_well]
                    protocol.comment(f"Small volumes found → creating intermediate mix in {intermediate_well_small}")

                    for vol, src in zip(small_volumes, small_sources):

                        if 0 < vol <= 50:
                            if not tips50_by_row:
                                swap_rack50()
                            p50.pick_up_tip(location=tips50_by_row.pop(0))
                            counter_50 += 1
                            counter_50_f += 1
                            p50.aspirate(vol, plasmid_plate[src])
                            p50.dispense(vol, plasmid_plate[intermediate_well_small])
                            p50.blow_out()
                            p50.drop_tip()
                        elif 50 < vol <= 200:
                            p1000.pick_up_tip(location=tips200_by_row.pop(0))
                            counter_200 += 1
                            p1000.aspirate(vol, plasmid_plate[src])
                            p1000.dispense(vol, plasmid_plate[intermediate_well_small])
                            p1000.blow_out()
                            p1000.drop_tip()

                    intermediate_well_final = assigned_final_wells[dest_well]
                    protocol.comment(f"Mix {dest_well}: final transfer → Eppendorf {intermediate_well_final}")

                    total_intermediate_volume = sum(small_volumes)
                    final_transfer = total_intermediate_volume / 10  # back to original scale

                    if final_transfer <= 50:
                        if not tips50_by_row:
                            swap_rack50()
                        p50.pick_up_tip(location=tips50_by_row.pop(0))
                        counter_50 += 1
                        counter_50_f += 1
                        p50.mix(3, 0.8 * total_intermediate_volume, plasmid_plate[intermediate_well_small].bottom(0.1))
                        p50.aspirate(final_transfer, plasmid_plate[intermediate_well_small].bottom(0.1))
                        p50.dispense(final_transfer, plasmid_plate[intermediate_well_final])
                        p50.blow_out()
                        p50.drop_tip()
                    else:
                        p1000.pick_up_tip(location=tips200_by_row.pop(0))
                        counter_200 += 1
                        p1000.aspirate(final_transfer, plasmid_plate[intermediate_well_small].bottom(0.1))
                        p1000.dispense(final_transfer, plasmid_plate[intermediate_well_final])
                        p1000.blow_out()
                        p1000.drop_tip()

                    protocol.comment(
                        f"Transferred intermediate mix ({final_transfer} µL) from {intermediate_well_final} to {dest_well}")

                else:

                    intermediate_well_final = assigned_final_wells[dest_well]
                    vol = small_volumes[0]/10
                    src = small_sources[0]

                    protocol.comment(
                        f"Only one small volume → directly transferring to final intermediate well {intermediate_well_final}")
                    if vol <= 0:
                        continue
                    if vol <= 50:
                        if not tips50_by_row:
                            swap_rack50()
                        p50.pick_up_tip(location=tips50_by_row.pop(0))
                        counter_50 += 1
                        counter_50_f += 1
                        p50.aspirate(vol, plasmid_plate[src])
                        p50.dispense(vol, plasmid_plate[intermediate_well_final])
                        p50.blow_out()
                        p50.drop_tip()
                    else:
                        p1000.pick_up_tip(location=tips200_by_row.pop(0))
                        counter_200 += 1
                        p1000.aspirate(vol, plasmid_plate[src])
                        p1000.dispense(vol, plasmid_plate[intermediate_well_final])
                        p1000.blow_out()
                        p1000.drop_tip()

                for vol, src in zip(normal_volumes, normal_sources):
                    if vol <= 0:
                        continue
                    pipette = p50 if vol <= 50 else p1000
                    if pipette == p50:
                        if not tips50_by_row:
                            swap_rack50()
                    pipette.pick_up_tip(location=tips50_by_row.pop(0) if pipette == p50 else tips200_by_row.pop(0))
                    if pipette == p50:
                        counter_50 += 1
                        counter_50_f += 1
                    else:
                        counter_200 += 1

                    pipette.aspirate(vol, plasmid_plate[src])
                    pipette.dispense(vol, plasmid_plate[intermediate_well_final])
                    pipette.blow_out(plasmid_plate[intermediate_well_final].top(-2))
                    pipette.drop_tip()

                total_volume = sum(v / mix_data['scale_factors'][0] for v in mix_data['volumes'] if v > 0)

                protocol.comment(f"→ Final transfer to PCR well {dest_well} ({total_volume:.2f} µL)")

                pipette = p50 if total_volume <= 50 else p1000

                if pipette == p50:
                    if not tips50_by_row:
                        swap_rack50()
                    pipette.pick_up_tip(location=tips50_by_row.pop(0))
                    counter_50 += 1
                    counter_50_f += 1
                else:
                    pipette.pick_up_tip(location=tips200_by_row.pop(0))
                    counter_200 += 1

                # Mixing before aspirating from intermediate_final well
                mix_vol = min(total_volume * 0.8, 50)
                pipette.mix(3, mix_vol, plasmid_plate[intermediate_well_final].bottom(1))

                pipette.aspirate(total_volume, plasmid_plate[intermediate_well_final].bottom(1))
                pipette.dispense(total_volume, pcr_plate[dest_well].bottom(1))
                pipette.blow_out(pcr_plate[dest_well].top(-2))
                pipette.drop_tip()

                protocol.comment(f"✅ Final transfer for mix {dest_well} COMPLETED")

            else:

            # --- Normal transfers (> 0.8 µL, excluding NaCl) ---
                for vol, src in zip(normal_volumes, normal_sources):
                    if vol <= 0:
                        continue
                    pipette = p50 if vol <= 50 else p1000
                    if pipette== p50:
                        if not tips50_by_row:
                            swap_rack50()
                    pipette.pick_up_tip(location=tips50_by_row.pop(0) if pipette == p50 else tips200_by_row.pop(0))
                    if pipette == p50:
                        counter_50 += 1
                        counter_50_f += 1
                    else:
                        counter_200 += 1

                    pipette.aspirate(vol, plasmid_plate[src])
                    pipette.dispense(vol, pcr_plate[dest_well])
                    pipette.blow_out(pcr_plate[dest_well].top(-2))
                    pipette.drop_tip()


    protocol.comment(f"\nProtocol complete. Created {mix_count} mixes including NaCl (150mM).")
    heater_shaker.open_labware_latch()
    print('Tips200 used:', counter_200)
    print('Tips50 used:', counter_50_f,'\n')
