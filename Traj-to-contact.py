#!/usr/bin/env python
'''
This program is used for calculating and plotting the evolution of contact number in a given pdb trajectory. 
Also, using the total number of contacts and percentage of native contacts as the reaction coordinates,
this program plots the heat map of (# contacts, % native contacts).

The distance between two residues can be defined in different ways:
1. the distance between a specific pair of atoms (i.e., CA-CA or CB-CB),
2. the shortest distance among the atoms belonging to residue i and those belonging to residue j
3. the distance between the centers of mass of the two residues
'''

__author__  = 'Wang Zongan'
__version__ = '2017-03-28'

import os
import sys 
import string
import numpy as np
import cPickle as cp
from itertools import combinations

import Bio.PDB

import mdtraj.core.element as el
import mdtraj as md
from mdtraj.formats.registry import FormatRegistry
angstrom=0.1  # conversion to nanometer from angstrom

import seaborn as sns
sns.set_style(style='white')
from matplotlib.pyplot import *

##<-------------------- protein basics -------------------->##
backbone = ['C','CA','N','O']

base_sc_ref = {
    'ALA': np.array([-0.01648328,  1.50453228,  1.20193768]),
    'ARG': np.array([-0.27385093,  3.43874264,  2.24442499]),
    'ASN': np.array([-0.27119135,  2.28878532,  1.32214314]),
    'ASP': np.array([-0.19836569,  2.23864046,  1.36505725]),
    'CYS': np.array([-0.17532601,  1.92513503,  1.34296652]),
    'GLN': np.array([-0.28652696,  2.84800873,  1.60009894]),
    'GLU': np.array([-0.26377398,  2.80887008,  1.69621717]),
    'GLY': np.array([-1.56136239e-02, 5.46052464e-01, -5.67664281e-19]),
    'HIS': np.array([-0.32896151,  2.66635893,  1.42411271]),
    'ILE': np.array([-0.23956042,  2.26489309,  1.49776818]),
    'LEU': np.array([-0.23949426,  2.67123263,  1.3032201 ]),
    'LYS': np.array([-0.26626635,  3.18256448,  1.85836641]),
    'MET': np.array([-0.21000946,  2.79544428,  1.52568726]),
    'PHE': np.array([-0.27214755,  2.83761534,  1.45094383]),
    'PRO': np.array([-1.10993493,  0.89959734,  1.41005877]),
    'SER': np.array([-0.00692474,  1.56683138,  1.475341  ]),
    'THR': np.array([-0.14662723,  1.80061252,  1.42785569]),
    'TRP': np.array([-0.01433503,  3.07506159,  1.56167948]),
    'TYR': np.array([-0.2841611 ,  3.02555746,  1.50123341]),
    'VAL': np.array([-0.02436993,  1.97251406,  1.32782961])}

model_geom = np.zeros((3,3))
model_geom[0] = (-1.19280531, -0.83127186, 0.)  # N
model_geom[1] = ( 0.,          0.,         0.)  # CA
model_geom[2] = ( 1.25222632, -0.87268266, 0.)  # C
model_geom -= model_geom.mean(axis=0)

three_letter_aa = dict(
    A='ALA', C='CYS', D='ASP', E='GLU', F='PHE', G='GLY', H='HIS', I='ILE', K='LYS', L='LEU', 
    M='MET', N='ASN', P='PRO', Q='GLN', R='ARG', S='SER', T='THR', V='VAL', W='TRP', Y='TYR')

aa_num = dict([(k,i) for i,k in enumerate(sorted(three_letter_aa.values()))])
one_letter_aa = dict([(v,k) for k,v in three_letter_aa.items()])


def rmsd_transform(target, model):
    assert target.shape == model.shape == (model.shape[0], 3)
    base_shift_target = target.mean(axis=0)
    base_shift_model  = model .mean(axis=0)

    target = target - target.mean(axis=0)
    model  = model  - model .mean(axis=0)

    R = np.dot(target.T, model)
    U,S,Vt = np.linalg.svd(R)
    if np.linalg.det(np.dot(U,Vt))<0.:
        Vt[:,-1] *= -1.  # fix improper rotation
    rot   = np.dot(U,Vt)
    shift = base_shift_target - np.dot(rot, base_shift_model)
    return rot, shift


def calculate_sidechain_CM(N, CA, C, resType):
    '''
    N, CA, C : coordinates of N, CA, C atoms of one given residue
    resType  : 3-letter aa type
    '''
    assert N.shape == CA.shape == C.shape == (3, )
    z = np.vstack((N, CA, C))
    #z = np.concatenate((N, CA, C), axis=0)
    rot, trans = rmsd_transform(z, model_geom)
    return np.dot(base_sc_ref[resType],rot.T) + trans


##<-------------------- John Jumper's functions for loading h5 file -------------------->##
## adpated so that I don't need to import mdtraj
def _output_groups(t):
    i=0
    while 'output_previous_%i'%i in t.root:
        yield t.get_node('/output_previous_%i'%i)
        i += 1
    if 'output' in t.root:
        yield t.get_node('/output')
        i += 1


def load_upside_traj(fname, sel='CM', stride=1, target_pos_only=False):
    import tables as tb
    with tb.open_file(fname) as t:
        start_frame = 0
        total_frames_produced = 0
        xyz = []
        if target_pos_only:
            xyz.append(t.root.target.pos[:,:,0])
            total_frames_produced = 1
            start_frame=1
        else:
            for g_no, g in enumerate(_output_groups(t)):
                # take into account that the first frame of each pos is the same as the last frame before restart
                # attempt to land on the stride
                sl = slice(start_frame,None,stride)
                xyz.append(g.pos[sl,0])
                total_frames_produced += g.pos.shape[0]-(1 if g_no else 0)  # correct for first frame
                start_frame = 1 + stride*(total_frames_produced%stride>0) - total_frames_produced%stride
        xyz = np.concatenate(xyz,axis=0)  # N, CA, C, (n_frame, 3*n_res, 3)
        seq = t.root.input.sequence[:]
    print "Finished loading upside trajectory."
    
    nmodel, nres = xyz.shape[0], len(seq)
    assert xyz.shape == (nmodel, nres*3, 3)
    coords = np.zeros((nmodel, nres, 3))
    if sel == 'CA':
        for nm in range(nmodel):
            for nr in range(nres):
                coords[nm][nr] = xyz[nm][nr*3+1]
    elif sel == 'CM':
        print "Now, use the static reference sidechain CM positions implied by N, CA, and C."
        for nm in range(nmodel):
            for nr in range(nres):
                coords[nm][nr] = calculate_sidechain_CM(xyz[nm][nr*3], xyz[nm][nr*3+1], xyz[nm][nr*3+2], seq[nr])
        print "Finished computing all referred sidechain positions."
    else:
        raise ValueError('--contact-type must be either CM or CA')
    return coords.astype('f4') 


##<-------------------- functions -------------------->##
def biopython_get_sidechain_weighted_CM_res(residue):
    '''
    residue : Bio.PDB.Residue object
    Note: not for GLY
    '''
    atoms = []
    for atom in res.get_atom():
        if atom not in backbone: # C, CA, N, O
            atoms.append(atom)
    coord = np.zeros(3)
    mass  = 0
    for atom in atoms:
        coord += atom.get_coord()*atom.mass
        mass  += atom.mass
    return coord/mass


def get_coordinates(structure, sel='CM', ref_sidechain_CM=True):
    '''
    structure : Bio.PDB structure object
    sel       : Only 3 options are available- CA, CB, CM

    Return
    coords    : in shape (nmodel, nres, 3)
    '''
    nmodel = len(structure)
    nres   = len([res for res in structure[0].get_residues() if res.get_id()[0] == ' '])
    if sel == 'CM':
        if ref_sidechain_CM:
            print "Now, use the static reference sidechain CM positions implied by N, CA, and C."
        else:
            print "Now, use the weighted sidechain CM positions given by the pdb file." 
            print "Be sure that the supplied PDB file has sidechains."

    coords = np.zeros((nmodel, nres, 3))
    for nm, model in enumerate(structure):
        residues = [res for res in structure[nm].get_residues() if res.get_id()[0] == ' ']
        assert len(residues) == nres
        
        for nr, res in enumerate(residues):
            if sel == 'CA':
                coords[nm][nr] = res[sel].get_coord()

            elif sel == 'CB':
                at = res[sel] if res.get_resname() != 'GLY' else res['CA']
                coords[nm][nr] = at.get_coord()

            elif sel == 'CM':
                if ref_sidechain_CM:
                    coords[nm][nr] = calculate_sidechain_CM(res['N'].get_coord(), res['CA'].get_coord(), res['C'].get_coord(), res.get_resname())
                else:
                    if res.get_resname() == 'GLY':
                        coords[nm][nr] = res['CA'].get_coord()
                    else:
                        coords[nm][nr] = biopython_get_sidechain_weighted_CM_res(res)  # sidechain includes CB
            else:
                raise ValueError('--contact-type must be either CM or CB or CA')
    return coords.astype('f4')


def compute_distances(coords, pairs):
    '''
    Input
    ----- -----
    coords: (nmodel, nres, 3), atom coordinates
    pairs : (N, 2), residue indices
                                                
    --> coords[:, pairs].shape = (nmodel, N, 2, 3)
    --> np.diff(coords[:, pairs], axis=2).shape = (nmodel, N, 1, 3)
    --> np.sum(np.diff(coords[:, pairs], axis=2)**2, axis=-1).shape = (nmodel, N, 1)

    Return
    ----- -----
    distances: (nmodel, N)
    '''
    return np.sqrt(np.sum(np.diff(coords[:, pairs], axis=2)**2, axis=-1))[:,:,0]


def generate_pairs(indices, threshold):
    '''
    indices : For example, [[1,2,3,4,5,6,7,8,9,10]] or [[1,2,3,4,5],[10,11,12,13,14,15,17,20,30]]

    --> 
    pairs : (N, 2)
    '''
    pairs = []
    if len(indices) == 1:
        for (res1, res2) in combinations(indices[0], 2):
            if np.absolute(res1-res2) > threshold:
                if res1 < res2:
                    pairs.append([res1, res2])
                else:
                    pairs.append([res2, res1])
    elif len(indices) == 2:
        for res1 in indices[0]:
            for res2 in indices[1]:
                if np.absolute(res1-res2) > threshold:
                    if res1 < res2:
                        pairs.append([res1, res2])
                    else:
                        pairs.append([res2, res1])
    else:
        raise ValueError('Please supply 2 residue groups at a time.')
    return np.array(pairs)


def residue_pair_id_dist(coords, indices, threshold, distance_cutoff):
    '''
    coords  : (nmodel, nres, 3)
    indices : For example, [[1,2,3,4,5,6,7,8,9,10]] or [[1,2,3,4,5],[10,11,12,13,14,15,17,20,30]]
    '''
    res_pairs = generate_pairs(indices, threshold)  # (N, 2) 

    if len(res_pairs) == 0:
        return [], []
    else:
        res_pair_distances = compute_distances(coords, res_pairs)  # (nmodel, N)
        
        res_pair_included          = []
        res_pair_distance_included = []
        for nm in range(len(res_pair_distances)):
            idx = np.where(res_pair_distances[nm] <= distance_cutoff)
            res_pair_included         .append(res_pairs             [idx])
            res_pair_distance_included.append(res_pair_distances[nm][idx])
        
        return res_pair_included, res_pair_distance_included


def find_contacts(coords, pairs):
    '''
    coords : (nmodel, nres, 3)
    pairs  : list of (N, 2) 
    
    --> 
    contacts : (nmodel, nres, nres)

    Note: contacts are symmatric, which means if residue pair (i,j) are in contact, both (i,j) and (j,i) are counted. 

    The returned the contacts are always for the whole protein, 
    however, only the contact pairs included will be counted in the matrix,
    which depends on the pairs. 
    '''
    nmodel = coords.shape[0]
    nres   = coords.shape[1]
    assert coords.shape == (nmodel, nres, 3)

    contacts = np.zeros((nmodel, nres, nres))
    for nm in range(nmodel):
        for (i, j) in pairs[nm]:
            contacts[nm][i][j] = contacts[nm][j][i] = 1

    return contacts

#def residue_distance_sidechainCM(res_1, res_2):
#    def residue_sidechainCM(res):
#        atoms = []
#        for atom in res.get_atom():
#            if atom not in backbone:
#                atoms.append(atom)
#        coord = np.zeros(3)
#        mass = 0
#        for atom in atoms:
#            coord += atom.get_coord()*atom.mass
#            mass += atom.mass
#        return coord/mass
#    res_1_coord = residue_sidechainCM(res_1)
#    res_2_coord = residue_sidechainCM(res_2)
#    diff_vec = res_1_coord - res_2_coord
#    return np.sqrt(np.sum(diff_vec*diff_vec,axis=0))


#def find_contact_distance_cutoff(structure, contact_type='CA', contact_cutoff=7.5):
#    nmodel = len(structure)
    # exclude het-residues and water molecules
#    nres = len([res for res in structure[0].get_residues() if res.get_id()[0] == ' '])

#    '''
#    <Yuan et al. BMC Bioinformatics 13 (2012) 292>
#    contact_type:
#    1. 'CA': CA-CA contact, default cutoff 7.5
#    2. 'CB': CB-CB contact, default cutoff 7.0
#    3. 'CM': sidechain CM-CM contact, default cutoff 6.5
#    '''
    # i: 0  ,...,n-5
    # j: i+4,...,n-1
#    contacts = np.zeros((nmodel, nres, nres))
#    for nm, model in enumerate(structure):
#        residues = [res for res in structure[nm].get_residues() if res.get_id()[0] == ' '] 
#        assert len(residues) == nres
#        for r1 in range(nres-4):
#            res_1 = residues[r1]
#            for r2 in range(r1+4,nres):
#                res_2 = residues[r2]
#                if contact_type == 'CA':
#                    dist = res_1['CA'] - res_2['CA']
#                elif contact_type == 'CB':
#                    res_1_atom = res_1['CB'] if res_1.get_resname() != 'GLY' else res_1['CA']
#                    res_2_atom = res_2['CB'] if res_2.get_resname() != 'GLY' else res_2['CA']
#                    dist = res_1_atom - res_2_atom
#                elif contact_type == 'CM':
#                    dist = residue_distance_sidechainCM(res_1, res_2)
#                if dist <= contact_cutoff:
#                    contacts[nm,r1,r2] = contacts[nm,r2,r1] = 1
#    return contacts


def find_native_contact(contacts, native_contact=None):
    if native_contact is not None:
        native_contact = native_contact[0]
        assert contacts[0].shape == native_contact.shape
    else:
        native_contact = contacts[0]
    return contacts * native_contact 


#def find_contacts_between_two_selections(contacts, sel1, sel2):
#    '''
#    Selectoins should be residue indices in 1D numpy array.
#    '''
#    assert set(sel1).intersect(sel2) == set()
#    return contacts[:,sel1,sel2]


def plot_contact_number_evolution(contacts, native_contact, contact_type, cutoff, plot_name, plot_format='png'):

    traj_native_contacts = find_native_contact(contacts, native_contact)

    if native_contact is not None:
        NC = np.sum(native_contact[0])/2
    else:
        NC = np.sum(contacts[0])/2

    fig = figure(figsize=(12,10))
    title('# Contacts V.S. Frame',fontsize=25)
    plot(np.sum(np.sum(            contacts, axis=-1), axis=-1)/2, color='green', label='# total contacts')
    plot(np.sum(np.sum(traj_native_contacts, axis=-1), axis=-1)/2, color=  'red', label='# native contacts')
   
    axhline(y=NC, color='blue', linewidth=2)
    
    tick_params(axis='both', which='major', labelsize=15)
    grid()
    legend(loc='upper left', fontsize='x-large')
    tight_layout()
    savefig('%s.contact_number_evolutoin.%s' % (plot_name, plot_format), format=plot_format)


def plot_heat_map_contact_number(
        contacts, native_contact, contact_type, cutoff,
        plot_name, plot_color_map='coolwarm', plot_format='png'):  
    
    if native_contact is not None:
        NC = np.sum(native_contact[0])/2
    else:
        NC = np.sum(contacts[0])/2

    number_contacts        = np.sum(np.sum(                                     contacts, axis=-1), axis=-1)/2
    number_native_contacts = np.sum(np.sum(find_native_contact(contacts, native_contact), axis=-1), axis=-1)/2

    # heatmap : ndarray, (nx, ny)
    heatmap, xedges, yedges = np.histogram2d(
            number_contacts, number_native_contacts, 
            bins=[np.linspace(number_contacts.min(), number_contacts.max(), 
                              number_contacts.max() -number_contacts.min()+1),
                  np.linspace(number_native_contacts.min(), number_native_contacts.max(), 
                              number_native_contacts.max() -number_native_contacts.min()+1)],
            normed=True)

    extent = (       number_contacts.min(),        number_contacts.max(), 
              number_native_contacts.min(), number_native_contacts.max())

    fig = figure(figsize=(12,10))
    suptitle('%s Contact Map: cutoff=%s' % (contact_type, str(cutoff)), fontsize=25, x=0.435, y=0.98)
    #title(pdbfile, fontsize=20)
    my_cmap = get_cmap(plot_color_map)
    my_cmap.set_under('w')

    imshow(heatmap, origin='low', cmap=my_cmap, extent=extent, aspect='auto')

    axvline(x=NC, color='green', linewidth=5)
    axhline(y=NC, color='green', linewidth=5)

    xlim(       number_contacts.min(),        number_contacts.max())
    ylim(number_native_contacts.min(), number_native_contacts.max())

    tick_params(axis='both', which='major', labelsize=15)
    fig.text(0.40, 0.03, '# total contacts' , ha='center', va='center', fontsize=25)
    fig.text(0.02, 0.50, '# native contacts', ha='center', va='center', fontsize=25, rotation='vertical')
    grid()

    cb = colorbar()
    #cb.set_label()
    tight_layout(rect=[0.03, 0.05, 1, 0.95]) # default is (0, 0, 1, 1) [left, bottom, right, top]
    savefig('%s.contact_number_heatmap.%s' % (plot_name, plot_format), format=plot_format)  


def parse_segments(s):
    ''' Parse segments of the form 10-30,50-60 '''
    import argparse
    import re

    if re.match('^([0-9]+(-[0-9]+)?)(,[0-9]+(-[0-9]+)?)*$', s) is None:
        raise argparse.ArgumentTypeError('segments must be of the form 10-30,45,72-76 or similar')

    def parse_seg(x):
        atoms = x.split('-')
        if len(atoms) == 1:
            return np.array([int(atoms[0])])
        elif len(atoms) == 2:
            return np.arange(int(atoms[0]),1+int(atoms[1]))  # inclusive on both ends
        else:
            raise RuntimeError('the impossible happened.  oops.')

    ints = np.concatenate([parse_seg(a) for a in s.split(',')])
    ints = np.array(sorted(set(ints)))   # remove duplicates and sort
    return ints


def sec_to_hr_min_sec(sec):
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return "%d:%02d:%02d" % (h, m, s)


bsnm = lambda fpath: os.path.splitext(os.path.basename(fpath))[0]


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description = 'Calculate and plot contact map for a given pdb file, ' +
                      'which can contain a trajectory of structures.',
        usage ='use "%(prog)s --help" for more information')
    parser.add_argument('h5', help='[required] input Upside-output H5 file')
 
    parser.add_argument('--contact-type', default='CM', type=str,
        help = 'Contact type, options are CA, CB, CM which stand for CA-CA contact, '+
               'CB-CB contact, and sidechain CM-CM contact, respectively. '+
               'Now all the contact types supported are distance cutoff contacts.' +
               'The default value is CM.')
    parser.add_argument('--contact-cutoff', default=6.5, type=float,
        help = 'Suggested values for CA, CB, and CM contacts are 7.5, 7.0, 6.5 A, respectively. ' +
               'The default value is 6.5 for the default CM contact.')
    parser.add_argument('--contact-primary-threshold', default=4, type=float,
        help = 'Suggested value is 4 as contacts are counted for non-neighboring residues.')
    parser.add_argument('--ref-sidechain', default=True, action='store_true', 
        help = 'Use sidechain postions inferred by C, N, CA. ' + 
               'You may want to use this for Upside trajectories.')

    parser.add_argument('--reference-model', default=None, type=str,
        help = 'If provided, the output plot of contact map will contain 2 parts, ' + 
               'the lower half being the contact map of the reference and ' + 
               'the upper half being the contact map of the pdb structure.')

    parser.add_argument('--residue-group', default=[], action='append', type=parse_segments,
        help = 'Two residue groups may be specified by giving the --residue-group flag 2 times. ' +
               'If 2 groups are supplied, the contacts between 2 parts/chains/domains will be calculated. ' +  
               'If only 1 residue group is provided, only the contacts of the residues within that group will be calculated. ' +
               'Note: residue indices start from 0.' )

    parser.add_argument('--plot-name', default=None, type=str, help = 'If turned on, plot.')
    parser.add_argument('--plot-color-map', default='coolwarm', type=str, 
        help = "Color map used in plotting, coolwarm by default. " +
               "Any color map supported by matplotlib can be used. " + 
               "Examples are: 'Blues', 'GnBu', 'BrBG', 'gist_rainbow', etc. " + 
               "(Ref: http://matplotlib.org/xkcd/examples/color/colormaps_reference.html)")
    parser.add_argument('--plot-format', default='png', type=str,
        help = 'Format of output plot, PNG format by default. ' +
               'Any format supported by matplotlib can be used.')
    
    parser.add_argument('--output-contact-id-dist-fname', default=None, type=str, 
        help = 'If turned on, output the file containing the ids and dists of the contacts.')
    parser.add_argument('--output-contact-number-fname', default=None, type=str, 
        help = 'If turned on, output the file containing the numbers of total contacts and native contacts.')

    args = parser.parse_args()

    # atoms selection & obtain coordinates
    #contacts = find_contact_distance_cutoff(struct, args.contact_type, args.contact_cutoff)
    #coords       = get_coordinates(struct, args.contact_type, args.ref_sidechain) 
    #nres    = len([res for res in struct[0].get_residues() if res.get_id()[0] == ' '])
    
    coords       = load_upside_traj(args.h5, args.contact_type)
    nmodel, nres = coords.shape[0], coords.shape[1]
    indices      = args.residue_group if args.residue_group else np.array([np.arange(nres)])
    pairs, dists = residue_pair_id_dist(coords, indices, args.contact_primary_threshold, args.contact_cutoff)
    contacts     = find_contacts(coords, pairs)
    print '=' * 40
    print '%i models detected in the pdb file.' % nmodel
    print '%i residues in the model'            % nres
    print '=' * 40

    if args.reference_model is not None:
        ref_structure        = Bio.PDB.PDBParser(QUIET=True).get_structure('protein', args.reference_model)
        ref_coords           = get_coordinates(ref_structure, args.contact_type, args.ref_sidechain)
        ref_indices          = args.residue_group if args.residue_group else np.array([np.arange(nres)])
        ref_pairs, ref_dists = residue_pair_id_dist(ref_coords, ref_indices, args.contact_primary_threshold, args.contact_cutoff)
        ref_contacts         = find_contacts(ref_coords, ref_pairs)
    else:
        ref_contacts=None
    
    if args.plot_name is not None:
        plot_contact_number_evolution(
                contacts, 
                native_contact = ref_contacts,
                contact_type   = args.contact_type, 
                cutoff         = args.contact_cutoff,
                plot_name      = args.plot_name,
                plot_format    = args.plot_format)

        if ref_contacts.sum() != 0:
            plot_heat_map_contact_number(
                contacts, 
                native_contact = ref_contacts,
                contact_type   = args.contact_type,
                cutoff         = args.contact_cutoff,
                plot_name      = args.plot_name,
                plot_color_map = args.plot_color_map,
                plot_format    = args.plot_format)

    if args.output_contact_id_dist_fname is not None:
        with open(args.output_contact_id_dist_fname, 'w') as f:
            cp.dump((pairs, dists), f, -1)
    
    if args.output_contact_number_fname is not None:
        traj_native_contacts = find_native_contact(contacts, ref_contacts)
        total_contacts_     = np.sum(np.sum(            contacts, axis=-1), axis=-1)
        total_nat_contacts_ = np.sum(np.sum(traj_native_contacts, axis=-1), axis=-1)
        with open(args.output_contact_number_fname, 'w') as f:
            for i in range(nmodel):
                f.write('%i %i\n' % (total_contacts_[i], total_nat_contacts_[i]))
        
    return True


if __name__ == '__main__':
    from time import time
    sta = time()
    main()
    print 'running time: %s' % sec_to_hr_min_sec(time() - sta)




