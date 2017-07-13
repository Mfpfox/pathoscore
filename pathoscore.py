from __future__ import print_function
import sys
import math
import toolshed as ts
from cyvcf2 import VCF
from sklearn.metrics import roc_curve, auc
import numpy as np
from matplotlib import pyplot as plt

cmd = "vcfanno -lua {lua} -p {p} {conf} {query_vcf} | bgzip -c > {out_vcf}"

def infos(path):
    infos = []
    for x in ts.nopen(path):
        if x[1] != "#": break
        if not "INFO" in x: continue
        infos.append(x.split("ID=")[1].split(",")[0])
    return infos

def evaluate(vcfs, fields, inverse_fields, prefix):
    scored = {}
    unscored = {}
    for f in fields + inverse_fields:
        scored[f] = [[], []]
        unscored[f] = 0

    #scored['comb'] = [[], []]
    #unscored['comb'] = 0
    fields = [(f, False) for f in fields] + [(f, True) for f in inverse_fields]
    common_pathogenic = 0

    for i, vcf in enumerate(vcfs):
        for v in VCF(vcf):
            is_pathogenic = int((len(vcfs) == 2 and i == 0) or (len(vcfs) == 1 and v.INFO.get('ispath') is not None))
            if is_pathogenic and v.INFO.get('_exclude'):
                common_pathogenic += 1
                continue

            for f, invert in fields:
                score = v.INFO.get(f)
                if score is None or score == "NA":
                    unscored[f] += 1
                    continue
                score = float(score)
                if math.isnan(score):
                    unscored[f] += 1
                    continue
                if invert:
                    score = -score

                scored[f][is_pathogenic].append(score)
            """
            ccr = v.INFO.get('exac_ccr')
            if ccr is None:
                unscored['comb'] += 1
                continue
            cadd = v.INFO.get('MPC')
            if cadd is None or cadd == "NA":
                unscored['comb'] += 1
                continue
            ccr, cadd = float(ccr), float(cadd) * 33
            if ccr < 1:
                scored['comb'][is_pathogenic].append(cadd)
            elif cadd > 50 and ccr > 50:
                scored['comb'][is_pathogenic].append(cadd)

    fields.append('comb')
            """

    for f, _ in fields:
        for i in (0, 1):
            arr = np.array(scored[f][i], dtype=float)
            if np.any(np.isinf(arr)):
                imax = np.max(arr[~np.isinf(arr)])
                arr[np.isinf(arr)] = imax
                scored[f][i] = list(arr)

    print(unscored)
    print("pathogenics excluded (via '_exclude' flag): %d" % common_pathogenic)
    from matplotlib import pyplot as plt
    import seaborn as sns
    sns.set_style('whitegrid')

    rocs = {}
    prcs = {}
    for f, _ in fields:
        scores = scored[f][0] + scored[f][1]
        truth = ([0] * len(scored[f][0])) + ([1] * len(scored[f][1]))
        fpr, tpr, _ = roc_curve(truth, scores, pos_label=1)
        auc_score = auc(fpr, tpr)
        rocs[f] = (tpr, fpr, auc_score)
        plt.plot(fpr, tpr, label=" %s auc: %.3f" % (f, auc_score))
        plt.plot([0, 1], [0, 1], linestyle='--')
    plt.xlim(0, 1)
    plt.ylim(0, 1)
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.legend(loc="lower right")
    plt.savefig(prefix + ".roc.png")
    plt.close()

    fig, axes = plt.subplots(len(fields), figsize=(9, 12))
    for i, (f, _) in enumerate(fields):
        ax = axes[i]

        vals = np.array(scored[f][0])
        step_plot(vals, ax, "#1111dd", label="benign", alpha=0.75)

        vals = np.array(scored[f][1])
        step_plot(vals, ax, "#dd1111", label="pathogenic", alpha=0.75)

        ax.set_xlabel(f)
        ax.set_ylabel("Frequency")

    axes[0].legend(loc='upper left')
    plt.savefig(prefix + ".step.png")


def annotate(args):
    scores = [x.split(":") for x in args.scores]
    assert all(len(x) == 4 for x in scores), "scores must be specified as quartets of path:dest:source:op"

    fh = open("x.conf", "w")
    lua_fields, names = [], []
    for q in args.query_vcf:
        lua_fields.extend('"%s"' % i for i in infos(q))
    for path, name, field, op in scores:
        names.append(name)
        lua_fields.append('"%s"' % name)
        if not field.isdigit():
            field = '"%s"' % field
            col = "fields"
        else:
            col = "columns"
        fh.write("""[[annotation]]
file="{path}"
names=["{name}"]
{col}=[{field}]
ops=["{op}"]
\n""".format(**locals()))

    if args.exclude:
        fh.write("""
[[annotation]]
file="{path}"
names=["_exclude"]
fields=["AF"]
ops=["flag"]
\n""".format(path=args.exclude))

    if args.pathogenic:
        fh.write("""
[[postannotation]]
name="ispath"
fields=[%s]
op="lua:%s"
type="Flag"
""" % (",".join(lua_fields), args.pathogenic))

    if args.conf:
        fh.write("\n")
        fh.write(open(args.conf).read())
    fh.close()

    outs = []
    if not args.lua:
        args.lua = """<(echo "")"""
    for i, query_vcf in enumerate(args.query_vcf):
        if len(args.query_vcf) == 2:
            outs.append(args.prefix + ".%d.vcf.gz" % ["pathogenic", "benign"][i])
        else:
            outs.append(args.prefix + ".vcf.gz")

        print(cmd.format(p=args.procs, conf=fh.name, query_vcf=query_vcf, out_vcf=outs[-1], lua=args.lua))
        list(ts.nopen("|" + cmd.format(p=args.procs, conf=fh.name, query_vcf=query_vcf, out_vcf=outs[-1], lua=args.lua)))
    #evaluate(outs, names, args.prefix)

def step_plot(vals, ax, color, **kwargs):
    p, p_edges = np.histogram(vals, bins=50, range=[vals.min(), vals.max()])
    sp = sum(p)
    p = [float(x) / sp for x in p]
    p.append(p[-1])
    with_p = p_edges[-1] - p_edges[0]
    ax.plot(p_edges, p, color=color, ls='steps', lw=1.9, **kwargs)

if __name__ == "__main__":
    from argparse import ArgumentParser

    p = ArgumentParser()
    subps = p.add_subparsers(help="sub-command", dest="command")

    ### annotation ###
    pan = subps.add_parser("annotate")
    pan.add_argument("--procs", "-p", default=3, help="number of processors to use for vcfanno")
    pan.add_argument("--prefix", default="pathoscore", help="prefix for output files")
    pan.add_argument("--pathogenic", help="expression indicating that a variant is pathogenic. (If 2 vcf files are given this is not needed)")
    pan.add_argument("--exclude", help="optional exclude vcf to filter supposed pathogenic variants (matches on REF and ALT)")
    pan.add_argument("--conf", help="optional vcfanno conf file that will also be used for annotation")
    pan.add_argument("--lua", help="optional path to lua file if it's needed by the --conf argument")
    pan.add_argument("--scores", "-s", action="append", help="format of path:name:field:op e.g. some.bed:myscore:4:self or cadd.vcf:cadd:PHRED:concat that give the path of the annotation file, the name in the output, and the column in the input respectively. may be specified multiple times. op is one of those specified here: https://github.com/brentp/vcfanno#operations")
    pan.add_argument("query_vcf", nargs="+", help="vcf(s) to annotate if 2 are specified it must be pathogenic and then benign")

    ### evaluation ###
    pev = subps.add_parser("evaluate")
    pev.add_argument("query_vcf", nargs="+", help="vcf(s) to annotate if 2 are specified it must be pathogenic and then benign")
    pev.add_argument("--score-columns", "-s", action="append", help="info fields on which to base evaluation.",
                     default=[])
    pev.add_argument("--inverse-score-columns", "-i", action="append", default=[],
            help="like score columns but lower score is more constrained")
    pev.add_argument("--prefix", default="pathoscore", help="prefix for output files")

    a = p.parse_args()
    print("TODO: implement postannotation (e.g. to do combined metrics)")

    if not len(a.query_vcf) in (1, 2):
        raise Exception("must specify 1 or 2 query vcfs")

    if a.command == "annotate":
        annotate(a)
    else:
        evaluate(a.query_vcf, a.score_columns, a.inverse_score_columns, a.prefix)

