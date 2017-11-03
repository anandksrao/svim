import sys
import math
import argparse
from time import time

import numpy as np
import matplotlib.pyplot as plt
import networkx as nx
from scipy import stats

from callPacParams import callPacParams
from semiglobal import nw_compute_matrix, get_end_of_alignment


def parse_arguments():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description="""""")
    parser.add_argument('fasta', type=argparse.FileType('r'))
    parser.add_argument('--debug', '-d', action='store_true')
    return parser.parse_args()


def read_fasta(file_handle):
    """Simple FASTA file reader. Store sequences in a dictionary with sequence names as keys."""
    sequences = dict()
    seq = ""
    for line in file_handle:
        stripped_line = line.strip()
        if stripped_line.startswith('>'):
            if len(seq) > 0:
                sequences[name] = seq
                seq = ""
            name = stripped_line[1:]
        else:
            seq += stripped_line
    if len(seq) > 0:
        sequences[name] = seq
    return sequences


def find_stretches(values, threshold=7, tolerance=2, min_length=3):
    """Finds all streaks of values larger than threshold. Gaps up to length tolerance are tolerated.
       Streaks must have a certain minimum length. Returns a list of tuples (start, inclusive end)"""
    stretches = []
    begin = -1
    last_good = -1
    for index, value in enumerate(values):
        if value > threshold:
            if begin == -1:
                begin = index
            last_good = index
        else:
            if begin != -1 and index - last_good > tolerance:
                if last_good - begin + 1 >= min_length:
                    stretches.append((begin, last_good))
                begin = -1
                last_good = -1
    if begin != -1 and last_good - begin >= min_length - 1:
        stretches.append((begin, last_good))
    return stretches


def convert_segments(segments):
    """Converts segments from diagonal-relative coordinates to x-y coordinates.
       A segment is a list of stretches. A stretch is a (offset, start, end) tuple."""
    converted_segments = []
    for segment in segments:
        stretches = []
        for offset, start, end in segment:
            if offset > 0:
                stretches.append(((start, start + offset), (end, end + offset)))
            else:
                stretches.append(((start - offset, start), (end - offset, end)))
        start = sorted(stretches, key=lambda stretch: stretch[0][0] + stretch[0][1])[0][0]
        end = sorted(stretches, key=lambda stretch: stretch[1][0] + stretch[1][1], reverse=True)[0][1]
        new_segment = {'start': start, 'end': end, 'stretches': stretches}
        converted_segments.append(new_segment)
    return converted_segments


def distance(point1, point2, parameters):
    """Compute distance between two points with convex gap costs.
       Point 2 must have higher x and y than point 1 (with a tolerance)."""
    if point2[0] + parameters.path_tolerance >= point1[0] and point2[1] + parameters.path_tolerance >= point1[1]:
        # distance in x direction
        if point2[0] - point1[0] <= 0:
            dist = 0
        else:
            dist = parameters.path_constant_gap_cost + (parameters.path_convex_gap_cost * math.log(point2[0] - point1[0]))
        # distance in y direction
        if point2[1] - point1[1] <= 0:
            dist += 0
        else:
            dist += parameters.path_constant_gap_cost + (parameters.path_convex_gap_cost * math.log(point2[1] - point1[1]))
        return dist
    else:
        return float("inf")


def find_best_path(segments, matrix_end, parameters, debug=False):
    """Find best path through alignment matrix using segments."""
    graph = nx.DiGraph()
    graph.add_nodes_from(["start", "end"])
    graph.add_edge("start", "end", weight=distance((0, 0), matrix_end, parameters))
    for i1, s1 in enumerate(segments):
        for i2, s2 in enumerate(segments):
            if i1 != i2:
                dist = distance(s1['end'], s2['start'], parameters)
                if dist < float('inf'):
                    graph.add_edge(i1, i2, weight=dist)
        dist = distance((0, 0), s1['start'], parameters)
        if dist < float('inf'):
            graph.add_edge("start", i1, weight=dist)
        dist = distance(s1['end'], matrix_end, parameters)
        if dist < float('inf'):
            graph.add_edge(i1, "end", weight=dist)
    if debug:
        print "Edge-list:", nx.to_edgelist(graph)
    shortest_path = nx.shortest_path(graph, "start", "end", weight="weight")
    start_segment = {'start': (0, 0), 'end': (0, 0), 'stretches': []}
    end_segment = {'start': matrix_end, 'end': matrix_end, 'stretches': []}
    return [start_segment] + [segments[node] for node in shortest_path[1:-1]] + [end_segment]


def plot_array(array, rows, cols, dataset, figure=1):
    """Plot an array using matplotlib."""
    plt.figure(figure)
    plt.subplot(rows, cols, dataset)
    plt.imshow(array)


def find_svs(ref, read, parameters, debug=False, times=False):
    """Identify SVs between reference and read by kmer counting."""
    start_time = time()

    # Determine size of counting matrix
    rows = len(ref) / parameters.count_win_size
    cols = len(read) / parameters.count_win_size
    last_row_size = len(ref) % parameters.count_win_size
    last_col_size = len(read) % parameters.count_win_size
    if last_row_size > (parameters.count_win_size / 3):
        rows += 1
    if last_col_size > (parameters.count_win_size / 3):
        cols += 1

    ########################
    # Step 1: Kmer counting#
    ########################
    s2 = time()
    counts = np.zeros((rows, cols), dtype=int)

    # Prepare kmer set for each read bucket
    ykmers = []
    for ybucket in xrange(cols):
        bucketkmers = set()
        for i in xrange(parameters.count_win_size):
            if (ybucket * parameters.count_win_size + i + parameters.count_k) <= len(read):
                bucketkmers.add(read[(ybucket * parameters.count_win_size + i): (ybucket * parameters.count_win_size + i + parameters.count_k)])
        ykmers.append(bucketkmers)

    for xbucket in xrange(rows):
        for i in xrange(parameters.count_win_size):
            for ybucket in xrange(cols):
                if (xbucket * parameters.count_win_size + i + parameters.count_k) <= len(ref):
                    if ref[(xbucket * parameters.count_win_size + i): (xbucket * parameters.count_win_size + i + parameters.count_k)] in ykmers[ybucket]:
                        counts[xbucket, ybucket] += 1

    if last_row_size > (parameters.count_win_size / 3):
        for col in xrange(len(read) / parameters.count_win_size):
            counts[rows - 1, col] = counts[rows - 1, col] * (parameters.count_win_size / last_row_size)
    if last_col_size > (parameters.count_win_size / 3):
        for row in xrange(len(ref) / parameters.count_win_size):
            counts[row, cols - 1] = counts[row, cols - 1] * (parameters.count_win_size / last_col_size)
    if last_row_size > (parameters.count_win_size / 3) and last_col_size > (parameters.count_win_size / 3):
        counts[rows - 1, cols - 1] = counts[rows - 1, cols - 1] * (parameters.count_win_size * parameters.count_win_size) / (last_row_size * last_col_size)

    if times:
        print "The size of the last row/column was {0}/{1}bps.".format(last_row_size, last_col_size)
        print "Counting finished ({0} s)".format(time() - s2)

    #############################
    # Step 2: Counts to Z-Scores#
    #############################
    s3 = time()
    counts2 = np.nan_to_num(stats.zscore(counts, axis=1) + stats.zscore(counts, axis=0))
    if times:
        print "Z-Score computation finished ({0} s)".format(time() - s3)

    ############################################
    # Step 3: Z-Scores to stretches to segments#
    ############################################
    # Compute boundaries of area where alignment path could possibly lay.
    if rows > cols:
        pos_lim = int(parameters.count_band * cols)
        neg_lim = - (rows - cols) - int(parameters.count_band * cols)
    else:
        pos_lim = int(parameters.count_band * rows) + (cols - rows)
        neg_lim = -int(parameters.count_band * rows)

    s4 = time()
    counts3 = np.zeros((rows, cols), dtype=int)
    completed_segments = []
    active_segments = []
    for offset in xrange(neg_lim, pos_lim):
        # Find stretches
        values = np.diagonal(counts2, offset)
        stretches = find_stretches(values, parameters.stretch_threshold, parameters.stretch_tolerance, parameters.stretch_min_length)

        # Visualize stretches
        for start, end in stretches:
            for i in xrange(start, end + 1):
                if offset >= 0:
                    counts3[i, i + offset] = 1
                else:
                    counts3[i - offset, i] = 1

        # Combine stretches to segment
        new_active_segments = []
        new_completed_segments = completed_segments + active_segments[:]
        for start, end in stretches:
            found_matching_segment = False
            for segment in active_segments:
                last_offset, last_start, last_end = segment[-1]
                if last_offset >= 0 and offset >= 0:
                    if start - 1 <= last_end and end >= last_start:
                        current_segment = segment[:]
                        current_segment.append((offset, start, end))
                        new_active_segments.append(current_segment)
                        if segment in new_completed_segments:
                            new_completed_segments.remove(segment)
                        found_matching_segment = True
                elif last_offset <= 0 and offset <= 0:
                    if start <= last_end and end + 1 >= last_start:
                        current_segment = segment[:]
                        current_segment.append((offset, start, end))
                        new_active_segments.append(current_segment)
                        if segment in new_completed_segments:
                            new_completed_segments.remove(segment)
                        found_matching_segment = True
            if not found_matching_segment:
                new_active_segments.append([(offset, start, end)])
        active_segments = new_active_segments
        completed_segments = new_completed_segments

    completed_segments.extend(active_segments)
    if times:
        print "Line finding finished ({0} s)".format(time() - s4)

    final_segments = convert_segments(completed_segments)
    if debug:
        print "Final segments", final_segments

    #########################################
    # Step 4: Path finding through segments #
    #########################################
    best_path = find_best_path(final_segments, (rows, cols), parameters, debug)

    ####################################
    # Step 5: Search best path for SVs #
    ####################################
    sv_results = []
    for index in xrange(len(best_path) - 1):
        # end coordinates are inclusive ==> therefore subtract 1 from gap length
        deletion_gap = best_path[index + 1]['start'][0] - best_path[index]['end'][0] - 1
        insertion_gap = best_path[index + 1]['start'][1] - best_path[index]['end'][1] - 1

        if insertion_gap > 1 or deletion_gap > 1:
            # Find exact start of deletion
            ref_window_start = (best_path[index]['end'][0], best_path[index]['end'][0] + 2)
            read_window_start = (best_path[index]['end'][1], best_path[index]['end'][1] + 2)
            matrix = nw_compute_matrix(ref[ref_window_start[0] * parameters.count_win_size: ref_window_start[1] * parameters.count_win_size],
                                       read[read_window_start[0] * parameters.count_win_size: read_window_start[1] * parameters.count_win_size], parameters.align_costs)
            start_i, start_j = get_end_of_alignment(matrix, (ref_window_start[1] - ref_window_start[0]) * parameters.count_win_size,
                                                    (read_window_start[1] - read_window_start[0]) * parameters.count_win_size, backwards=False)
            # alin_a, alin_b = nw_get_alignment(ref[ref_window_start[0] * parameters.count_win_size : ref_window_start[1] * parameters.count_win_size], read[read_window_start[0] * parameters.count_win_size : read_window_start[1] * parameters.count_win_size], matrix, parameters.align_costs)
            # print "End of segment:"
            # print_alignment(alin_a, alin_b)

            # Find exact end of deletion
            ref_window_end = (max(best_path[index + 1]['start'][0] - 1, 0), best_path[index + 1]['start'][0] + 1)
            read_window_end = (max(best_path[index + 1]['start'][1] - 1, 0), best_path[index + 1]['start'][1] + 1)
            matrix = nw_compute_matrix(ref[ref_window_end[0] * parameters.count_win_size: ref_window_end[1] * parameters.count_win_size],
                                       read[read_window_end[0] * parameters.count_win_size: read_window_end[1] * parameters.count_win_size], parameters.align_costs, backwards=True)
            end_i, end_j = get_end_of_alignment(matrix, (ref_window_end[1] - ref_window_end[0]) * parameters.count_win_size,
                                                (read_window_end[1] - read_window_end[0]) * parameters.count_win_size, backwards=True)
            # alin_a, alin_b = nw_get_alignment(ref[ref_window_end[0] * parameters.count_win_size : ref_window_end[1] * parameters.count_win_size], read[read_window_end[0] * parameters.count_win_size : read_window_end[1] * parameters.count_win_size], matrix, parameters.align_costs, backwards = True)
            # print "Start of segment:"
            # print_alignment(alin_a, alin_b, backwards=True)

            if insertion_gap > 1:
                # print "Insertion found:", best_path[index]['end'][1], best_path[index+1]['start'][1]
                # insertion_length = best_path[index+1]['start'][1] - best_path[index]['end'][1]
                insertion_length = read_window_end[0] * parameters.count_win_size + end_j - read_window_start[0] * parameters.count_win_size + start_j
                # sv_results.append( ('ins', best_path[index]['end'][0], best_path[index]['end'][0] + insertion_length) )
                sv_results.append(
                    ('ins', ref_window_start[0] * parameters.count_win_size + start_i, ref_window_start[0] * parameters.count_win_size + start_i + insertion_length))
            if deletion_gap > 1:
                # print "Deletion found:", best_path[index]['end'][0], best_path[index+1]['start'][0]
                # sv_results.append( ('del', best_path[index]['end'][0], best_path[index+1]['start'][0]) )
                sv_results.append(('del', ref_window_start[0] * parameters.count_win_size + start_i, ref_window_end[0] * parameters.count_win_size + end_i))

    total_time = time() - start_time
    if times:
        print "Total time: {0}s".format(total_time)
    if debug:
        return sv_results, counts, counts2, counts3

    return sv_results


def main():
    options = parse_arguments()
    parameters = callPacParams()

    # Read fasta file
    sequences = read_fasta(options.fasta)

    for i, d in enumerate(xrange(16, 24, 1)):
        print "Read", d
        for key in sequences.keys():
            if key.startswith("ref" + str(d)):
                ref = sequences[key]
            if key.startswith("read" + str(d)):
                read = sequences[key]
        sv_results, counts, zscores, stretches = find_svs(ref, read, parameters, debug=True)
        plot_array(counts, 4, 2, i + 1, 1)
        plot_array(zscores, 4, 2, i + 1, 2)
        plot_array(stretches, 4, 2, i + 1, 3)
        print sv_results
        print("")
    plt.show()


if __name__ == "__main__":
    sys.exit(main())