import os
import logging

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from svim.SVIM_clustering import partition_and_cluster_unilocal, partition_and_cluster_bilocal
from svim.SVSignature import SignatureTranslocation


def complete_translocations(translocation_signatures):
    """Generate a complete list of translocation by adding all reversed translocations"""

    reversed_translocations = []
    for signature in translocation_signatures:
        reversed_translocations.append(SignatureTranslocation(signature.contig2, signature.pos2, 'fwd' if signature.direction2 == 'rev' else 'rev', signature.contig1, signature.pos1, 'fwd' if signature.direction1 == 'rev' else 'rev', signature.signature, signature.read))
    return translocation_signatures + reversed_translocations


def cluster_sv_signatures(sv_signatures, options):
    """Takes a list of SVSignatures and splits them up by type. The SVSignatures of each type are clustered and returned as a tuple of
    (deletion_signature_clusters, insertion_signature_clusters, inversion_signature_clusters, tandem_duplication_signature_clusters, insertion_from_signature_clusters, completed_translocation_signatures)."""

    deletion_signatures = [ev for ev in sv_signatures if ev.type == 'del']
    insertion_signatures = [ev for ev in sv_signatures if ev.type == 'ins']
    inversion_signatures = [ev for ev in sv_signatures if ev.type == 'inv']
    tandem_duplication_signatures = [ev for ev in sv_signatures if ev.type == 'dup']
    translocation_signatures = [ev for ev in sv_signatures if ev.type == 'tra']
    insertion_from_signatures = [ev for ev in sv_signatures if ev.type == 'ins_dup']

    # Cluster SV signatures
    deletion_signature_clusters = partition_and_cluster_unilocal(deletion_signatures, options, "deleted regions")
    insertion_signature_clusters = partition_and_cluster_unilocal(insertion_signatures, options, "inserted regions")
    inversion_signature_clusters = partition_and_cluster_unilocal(inversion_signatures, options, "inverted regions")
    tandem_duplication_signature_clusters = partition_and_cluster_bilocal(tandem_duplication_signatures, options, "tandem duplicated regions")
    insertion_from_signature_clusters = partition_and_cluster_bilocal(insertion_from_signatures, options, "inserted regions with detected region of origin")

    return (deletion_signature_clusters, insertion_signature_clusters, inversion_signature_clusters, tandem_duplication_signature_clusters, insertion_from_signature_clusters, complete_translocations(translocation_signatures))


def write_signature_clusters_bed(working_dir, clusters):
    """Write signature clusters into working directory in BED format."""
    deletion_signature_clusters, insertion_signature_clusters, inversion_signature_clusters, tandem_duplication_signature_clusters, insertion_from_signature_clusters, completed_translocations = clusters

    # Print SV signature clusters
    if not os.path.exists(working_dir + '/signatures'):
        os.mkdir(working_dir + '/signatures')
    deletion_signature_output = open(working_dir + '/signatures/del.bed', 'w')
    insertion_signature_output = open(working_dir + '/signatures/ins.bed', 'w')
    inversion_signature_output = open(working_dir + '/signatures/inv.bed', 'w')
    tandem_duplication_signature_source_output = open(working_dir + '/signatures/dup_tan_source.bed', 'w')
    tandem_duplication_signature_dest_output = open(working_dir + '/signatures/dup_tan_dest.bed', 'w')
    translocation_signature_output = open(working_dir + '/signatures/trans.bed', 'w')
    insertion_from_signature_output = open(working_dir + '/signatures/ins_dup.bed', 'w')

    for cluster in deletion_signature_clusters:
        print(cluster.get_bed_entry(), file=deletion_signature_output)
    for cluster in insertion_signature_clusters:
        print(cluster.get_bed_entry(), file=insertion_signature_output)
    for cluster in inversion_signature_clusters:
        print(cluster.get_bed_entry(), file=inversion_signature_output)
    for cluster in tandem_duplication_signature_clusters:
        bed_entries = cluster.get_bed_entries()
        print(bed_entries[0], file=tandem_duplication_signature_source_output)
        print(bed_entries[1], file=tandem_duplication_signature_dest_output)
    for cluster in insertion_from_signature_clusters:
        bed_entries = cluster.get_bed_entries()
        print(bed_entries[0], file=insertion_from_signature_output)
        print(bed_entries[1], file=insertion_from_signature_output)
    for translocation in completed_translocations:
        print("{0}\t{1}\t{2}\t{3}\t{4}\t{5}".format(translocation.contig1, translocation.pos1, translocation.pos1+1, ">{0}:{1}".format(translocation.contig2, translocation.pos2), translocation.signature, translocation.read), file=translocation_signature_output)

    deletion_signature_output.close()
    insertion_signature_output.close()
    inversion_signature_output.close()
    tandem_duplication_signature_source_output.close()
    tandem_duplication_signature_dest_output.close()
    translocation_signature_output.close()
    insertion_from_signature_output.close()


def write_signature_clusters_vcf(working_dir, clusters, version):
    """Write signature clusters into working directory in VCF format."""
    deletion_signature_clusters, insertion_signature_clusters, inversion_signature_clusters, tandem_duplication_signature_clusters, insertion_from_signature_clusters, completed_translocations = clusters

    if not os.path.exists(working_dir + '/signatures'):
        os.mkdir(working_dir + '/signatures')
    vcf_output = open(working_dir + '/signatures/all.vcf', 'w')

    # Write header lines
    print("##fileformat=VCFv4.3", file=vcf_output)
    print("##source=SVIMV{0}".format(version), file=vcf_output)
    print("##ALT=<ID=DEL,Description=\"Deletion\">", file=vcf_output)
    print("##ALT=<ID=INV,Description=\"Inversion\">", file=vcf_output)
    print("##ALT=<ID=DUP,Description=\"Duplication\">", file=vcf_output)
    print("##ALT=<ID=DUP:TANDEM,Description=\"Tandem Duplication\">", file=vcf_output)
    print("##ALT=<ID=INS,Description=\"Insertion\">", file=vcf_output)
    print("##INFO=<ID=END,Number=1,Type=Integer,Description=\"End position of the variant described in this record\">", file=vcf_output)
    print("##INFO=<ID=SVTYPE,Number=1,Type=String,Description=\"Type of structural variant\">", file=vcf_output)
    print("##INFO=<ID=SVLEN,Number=.,Type=Integer,Description=\"Difference in length between REF and ALT alleles\">", file=vcf_output)
    print("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO", file=vcf_output)

    vcf_entries = []
    for cluster in deletion_signature_clusters:
        vcf_entries.append((cluster.get_source(), cluster.get_vcf_entry()))
    for cluster in insertion_signature_clusters:
        vcf_entries.append((cluster.get_source(), cluster.get_vcf_entry()))
    for cluster in inversion_signature_clusters:
        vcf_entries.append((cluster.get_source(), cluster.get_vcf_entry()))
    for cluster in tandem_duplication_signature_clusters:
        vcf_entries.append((cluster.get_source(), cluster.get_vcf_entry()))

    # Sort and write entries to VCF
    for source, entry in sorted(vcf_entries, key=lambda pair: pair[0]):
        print(entry, file=vcf_output)

    vcf_output.close()


def plot_histograms(working_dir, clusters):
    deletion_signature_clusters, insertion_signature_clusters, inversion_signature_clusters, tandem_duplication_signature_clusters, insertion_from_signature_clusters, completed_translocations = clusters

    if not os.path.exists(working_dir + '/signatures'):
        os.mkdir(working_dir + '/signatures')
    pdf = PdfPages(working_dir + '/signatures/signature_cluster_histograms.pdf')
    fig = plt.figure()
    fig.suptitle('Deleted region signature clusters', fontsize=10)

    plt.subplot(2, 1, 1)
    deletion_scores = [del_cluster.score for del_cluster in deletion_signature_clusters]
    plt.hist(deletion_scores, bins=100)
    plt.xlabel('Score')
    plt.ylabel('Count')
    plt.yscale('log', nonposy='clip')
    plt.title('Histogram of Score')
    plt.grid(True)

    plt.subplot(2, 1, 2)
    deletion_sizes = [del_cluster.end - del_cluster.start for del_cluster in deletion_signature_clusters]
    plt.hist(deletion_sizes, bins=20)
    plt.xlabel('Size in bp')
    plt.ylabel('Count')
    plt.yscale('log', nonposy='clip')
    plt.title('Histogram of Size')
    plt.grid(True)

    pdf.savefig(fig)

    fig = plt.figure()
    fig.suptitle('Inserted regions', fontsize=10)

    plt.subplot(2, 1, 1)
    insertion_scores = [ins_cluster.score for ins_cluster in insertion_signature_clusters]
    plt.hist(insertion_scores, bins=100)
    plt.xlabel('Score')
    plt.ylabel('Count')
    plt.yscale('log', nonposy='clip')
    plt.title('Histogram of Score')
    plt.grid(True)

    plt.subplot(2, 1, 2)
    insertion_sizes = [ins_cluster.end - ins_cluster.start for ins_cluster in insertion_signature_clusters]
    plt.hist(insertion_sizes, bins=20)
    plt.xlabel('Size in bp')
    plt.ylabel('Count')
    plt.yscale('log', nonposy='clip')
    plt.title('Histogram of Size')
    plt.grid(True)

    pdf.savefig(fig)

    fig = plt.figure()
    fig.suptitle('Inverted regions', fontsize=10)

    plt.subplot(2, 1, 1)
    inversion_scores = [inv_cluster.score for inv_cluster in inversion_signature_clusters]
    plt.hist(inversion_scores, bins=100)
    plt.xlabel('Score')
    plt.ylabel('Count')
    plt.yscale('log', nonposy='clip')
    plt.title('Histogram of Score')
    plt.grid(True)

    plt.subplot(2, 1, 2)
    inversion_sizes = [inv_cluster.end - inv_cluster.start for inv_cluster in inversion_signature_clusters]
    plt.hist(inversion_sizes, bins=20)
    plt.xlabel('Size in bp')
    plt.ylabel('Count')
    plt.yscale('log', nonposy='clip')
    plt.title('Histogram of Size')
    plt.grid(True)

    pdf.savefig(fig)

    pdf.close()
