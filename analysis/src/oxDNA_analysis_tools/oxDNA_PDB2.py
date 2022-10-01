#!/usr/bin/env python

import sys
import os
import numpy as np
import copy
import argparse
import string
from collections import defaultdict
from math import sqrt, sin

from oxDNA_analysis_tools.UTILS.pdb import Atom, Nucleotide, AminoAcid, FROM_OXDNA_TO_ANGSTROM
from oxDNA_analysis_tools.UTILS.RyeReader import get_confs, describe, strand_describe, get_input_parameter, inbox
import oxDNA_analysis_tools.UTILS.protein_to_pdb as pro
import oxDNA_analysis_tools.UTILS.utils as utils

DD12_PDB_PATH = "./UTILS/dd12_na.pdb"

number_to_base = {0 : 'A', 1 : 'G', 2 : 'C', 3 : 'T'}


base_to_number = {'A' : 0, 'a' : 0, 'G' : 1, 'g' : 1,
                  'C' : 2, 'c' : 2, 'T' : 3, 't' : 3,
                  'U' : 3, 'u' : 3, 'D' : 4}
                  
aa_to_number = {'A':-1, 'R':-2, 'N':-3, 'D':-4, 'C':-5, 
                'E':-6, 'Q':-7, 'G':-8, 'H':-9, 'I':-10, 
                'L':-11, 'K':-12, 'M':-13, 'F':-14, 
                'P':-15, 'S':-16, 'T':-17, 'W':-18, 
                'Y':-19, 'V':-20, 'Z':-21, 'X':0}

number_to_aa = {-1:'A', -2:'R', -3:'N', -4:'D', -5:'C', 
                -6:'E', -7:'Q', -8:'G', -9:'H', -10:'I', 
                -11:'L', -12:'K', -13:'M', -14:'F', 
                -15:'P', -16:'S', -17:'T', -18:'W', 
                -19:'Y', -20:'V', -21:'Z', 0:'X'}

def align(full_base, ox_base):
        theta = utils.get_angle(full_base.a3, ox_base._a3)
        # if the two bases are already essentially aligned then we do nothing
        if sin(theta) > 1e-3:
            axis = np.cross(full_base.a3, ox_base._a3)
            axis /= sqrt(np.dot(axis, axis))
            R = utils.get_rotation_matrix(axis, theta)
            full_base.rotate(R)
    
        theta = utils.get_angle(full_base.a1, ox_base._a1)
        if sin(theta) > 1e-3:
            axis = np.cross(full_base.a1, ox_base._a1)
            axis /= sqrt(np.dot(axis, axis))
            R = utils.get_rotation_matrix(axis, theta)
            full_base.rotate(R)

def cli_parser():
    parser = argparse.ArgumentParser(prog=os.path.basename(
        __file__), description="Convert oxDNA files to PDB.  This converter can handle oxDNANM protein simulation files.")
    parser.add_argument('input', type=str, nargs=1,
                        help='the input file used to run the oxDNA simulation')
    parser.add_argument('configuration', type=str, nargs=1,
                        help='the configuration file you wish to convert')
    parser.add_argument('direction', type=str, nargs=1,
                        help='the direction of strands in the oxDNA files, either 35 or 53.  Most oxDNA files are 3-5.')
    parser.add_argument('pdbfiles', type=str, nargs='?',
                        help='PDB files for the proteins present in your structure.  If you have multiple proteins, you must specify multiple PDB files.')
    parser.add_argument('-H', '--hydrogen', action='store_true', default=True,
                        help='if you want to include hydrogen atoms in the output PDB file')
    parser.add_argument('-u', '--uniform-residue-names', action='store_true', default=False,
                        help='if you want to use uniform residue names in the output PDB file')
    parser.add_argument('-o', '--one_file_per_strand', action='store_true',
                        default=False, help='if you want to have one PDB file per strand')
    parser.add_argument('-s', '--same-pdb-all-protein-strands', action='store_true',
                        default=False, help='if you want to have the same PDB file for all protein strands')
    parser.add_argument('-r', '--rmsf-file', dest='rmsf_bfactor', type=str, nargs=1, 
                        help='A RMSF file from deviations.  Will be used to fill the b-factors field in the output PDB (only for D(R)NA)')
    return parser


def main():
    parser = cli_parser(os.path.basename(__file__))
    args = parser.parse_args()

    inputfile = args.input[0]
    conf_file = args.configuration[0]
    top_file = get_input_parameter(inputfile, "topology")
    direction = args.direction[0]
    if direction not in ["35", "53"]:
        print("Error: direction must be either 35 or 53")
        sys.exit(1)

    if args.pdbfiles:
        protein_pdb_files = args.pdbfiles
    else:
        protein_pdb_files = None

    oxDNA_direction = 1 if direction == "35" else 0
    hydrogen = args.hydrogen
    uniform_residue_names = args.uniform_residue_names
    one_file_per_strand = args.one_file_per_strand
    same_pdb_all_protein_strands = args.same_pdb_all_protein_strands

    top_info, traj_info = describe(top_file, conf_file)
    system, monomers = strand_describe(top_file)

    # Open PDB File of nice lookin duplex
    with open(os.path.join(os.path.dirname(__file__), DD12_PDB_PATH)) as f:
        nucleotides = []
        aminoacids = []
        old_residue = ""
        for line in f.readlines():
            if len(line) > 77:
                na = Atom(line)
                if na.residue_idx != old_residue:
                    nn = Nucleotide(na.residue, na.residue_idx)
                    nucleotides.append(nn)
                    old_residue = na.residue_idx
                nn.add_atom(na)

    bases = {}
    for n in nucleotides:
        n.compute_as()
        if n.base in bases:
            if n.check < bases[n.base].check:
                bases[n.base] = copy.deepcopy(n)
        else:
            bases[n.base] = n

    for n in nucleotides:
        n.a1, n.a2, n.a3 = utils.get_orthonormalized_base(n.a1, n.a2, n.a3)

    system, elements = strand_describe(top_file)
    ti, di = describe(top_file, conf_file)
    conf = get_confs(ti, di, 0, 1)[0]

    rmsf_file = args.rmsf_bfactor
    if rmsf_file:
        with open(rmsf_file) as f:
            try:
                # .json format from oat deviations
                substrings = f.read().split("[")[1].split("]")[0].split(",")
            except Exception as e:
                print("Parsing error in RMSF file. Invalid Format: %s" % e, file=sys.stderr)
                exit(1)
            try:
                rmsf_per_nucleotide = {i: float(s) for i, s in enumerate(substrings)}
            except Exception as e:
                print("Parsing error in RMSF file. Conversion to float failed : %s" % e, file=sys.stderr)
                exit(1)
    else:
        rmsf_per_nucleotide = defaultdict(lambda: 1.00)

    ox_nucleotides = []
    
    conf = inbox(conf, center=True)
    box_angstrom = conf.box * FROM_OXDNA_TO_ANGSTROM

    if np.any(box_angstrom[box_angstrom > 999]):
        print("At least one of the box sizes is larger than 999: all the atoms which are outside of the box will be brought back through periodic boundary conditions", file=sys.stderr)
        correct_for_large_boxes = True

    if one_file_per_strand:
        out_name = conf_file+"_1.pdb"
    else:
        out_name = conf_file+".pdb"

    with open(out_name, 'w+') as out:
        current_base_identifier = 'A'   
        reading_position = 0 

        if protein_pdb_files:
            s_pdbfile = iter(protein_pdb_files)
            pdbfile = next(s_pdbfile)        

        for s_id, strand in enumerate(system.strands):
            strand_pdb = []
            nucleotides_in_strand = strand.nucleotdies
            if not oxDNA_direction:
                nucleotides_in_strand = reversed(nucleotides_in_strand)

            print("\rINFO: Converting strand {}".format(strand.id))

            # Handle protein
            if strand.id < 0 and protein_pdb_files:
                coord = [conf.positions[m.id] for m in strand.monomers]  # amino acids only go from nterm to cterm (pdb format does as well)
                next_reading_position = pro.oxdna_to_pdb(out, coord, pdbfile, np.array([0, 0, 0]), reading_position)
                if next_reading_position == -1:
                    try:
                        pdbfile = next(s_pdbfile)
                        reading_position = 0
                    except StopIteration:
                        continue
                else:
                     reading_position = next_reading_position
            elif strand.id < 0 and not protein_pdb_files:
                print("ERROR: You must provide the PDB files for proteins in the scene")
                exit(1)

            # Nucleic Acids
            elif strand.index >= 0:
                for n_idx, nucleotide in enumerate(nucleotides_in_strand, 1):
                    if type(nucleotide.type) != str:
                        nb = number_to_base[nucleotide.type]
                    else: 
                        nb = nucleotide.type
                    my_base = copy.deepcopy(bases[nb])
                    my_base.chain_id = nucleotide.strand
                    residue_type = ""

                    # 3' end
                    if nucleotide == strand._nucleotides[0] and not strand._circular:
                        residue_type = "3"
                    # 5' end
                    elif nucleotide == strand._nucleotides[-1]:
                        residue_type = "5" 

                    if uniform_residue_names == True:
                        residue_suffix = ""
                    else:
                        residue_suffix = residue_type

                    align(my_base, nucleotide)
                    my_base.set_base(conf.positions[nucleotide.id] * FROM_OXDNA_TO_ANGSTROM)

                    if correct_for_large_boxes:
                        my_base.correct_for_large_boxes(box_angstrom)

                    residue_serial = n_idx % 9999
                    base_identifier = current_base_identifier
                    # Make nucleotide line from pdb.py
                    nucleotide_pdb = my_base.to_pdb(
                        base_identifier,
                        hydrogen,
                        residue_serial,
                        residue_suffix,
                        residue_type,
                        bfactor=rmsf_per_nucleotide[nucleotide.id],
                    )
                    # Append to strand_pdb
                    strand_pdb.append(nucleotide_pdb)

                print("\n".join(x for x in strand_pdb), file=out)
                print("TER", file=out)

            if one_file_per_strand:
                out.close()
                print("INFO: Wrote strand {}'s data to {}".format (s_id + 1, out_name))
                if strand != system.strands[-1]:
                    out_name = conf_file + "_{}.pdb".format(s_id + 2, )
                    out = open(out_name, "w")
            else:
                # we update the base identifier only if a single file is printed
                if current_base_identifier == 'Z':
                    current_base_identifier = 'A'
                else:
                    current_base_identifier = chr(ord(current_base_identifier) + 1)

        if protein_pdb_files:  
            # #Must Now renumber and restrand, (sorry)
            out.seek(0)
            outw = open('TM2.pdb', 'w')
            resid, atmid, chainid = -1, 1, -1
            #check against next atom entry
            pres, pchain = 0, 0
            alpha = list(string.ascii_uppercase)
            alpha = list(string.ascii_uppercase)
            a2 = copy.deepcopy(alpha)
            for i in range(26):
                alpha += [a2[i]+x for x in a2]
            for line in out:
                write_chain_end = False
                if line.startswith('ATOM'):
                    data = line.split()
                    cres_id = data[5]
                    curr_chainid = data[4]
                    if curr_chainid != pchain:
                        if chainid != -1:
                            write_chain_end = True
                        chainid += 1
                        pchain = curr_chainid 
                    if cres_id != pres:
                        resid += 1
                        pres = cres_id
                    data[1] = str(atmid)
                    data[5] = str(resid + 1)
                    data[4] = alpha[chainid]

                    coord = line[29:53]
                    xd, yd, zd = float(line[30:38]), float(line[38:46]), float(line[46:54])
                    for x in [xd, yd, zd]:
                        spcs = 7-len(str(x))
                        x = ''.join([' ' for i in range(spcs)]) + str(x)
                    #print(xd, yd, zd)
                    if len(list(data[-1])) == 1:
                        del data[-1]

                    if len(data) == 8:
                        try:
                            bfactor = float(data[7])
                            occ = float(data[6])
                        except ValueError:
                            occ = data[7][:4]
                            bfactor = data[7][4:]
                    elif len(data) == 9:
                        try:
                            bfactor = float(data[8])
                            occ = float(data[7])
                        except ValueError:
                            occ = data[8][:4]
                            bfactor = data[8][4:]
                    elif len(data) == 10:
                        try:
                            bfactor = float(data[9])
                            occ = float(data[8])
                        except ValueError:
                            occ = data[9][:4]
                            bfactor = data[9][4:]
                    elif len(data) == 11:
                        try:
                            bfactor=float(data[10])
                            occ = float(data[9])
                        except ValueError:
                            occ = data[10][:4]
                            bfactor = data[10][4:]
                    else: 
                        bfactor=0
                        occ = 1

                    for x in [occ, bfactor]:
                        spcs = 4-len(str(x))
                        x = ''.join([' ' for i in range(spcs)]) + str(x)

                    # data indice -> PDB FIELD LENGTH
                    dls = {1: 6, 2:4, 3:3, 4:2, 5:6}
                    for i in range(1,6):
                        x = len(data[i])
                        if x != dls[i]:
                            diff = dls[i] - x
                            empty = [' ' for j in range(diff)]
                            data[i] = ''.join(empty)+data[i]
                            #print(data[i])


                    print('ATOM', data[1], data[2], data[3], data[4], data[5], coord, occ, bfactor, file=outw)
                    if write_chain_end:
                        print('TER ', data[1], '    ', data[4], data[5], file=outw)
                    atmid += 1

    if not one_file_per_strand:
        outw.close()
        print("INFO: Wrote data to '{}'".format(out_name), file=sys.stderr)
        
    print("INFO: DONE", file=sys.stderr)

if __name__ == '__main__':
    main()
