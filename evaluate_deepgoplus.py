#!/usr/bin/env python

import numpy as np
import pandas as pd
import click as ck
from sklearn.metrics import classification_report
from sklearn.metrics.pairwise import cosine_similarity
import sys,pickle
from collections import deque
import time
import logging
from sklearn.metrics import roc_curve, auc, matthews_corrcoef
from scipy.spatial import distance
from scipy import sparse
import math
from utils import FUNC_DICT, Ontology, NAMESPACES
from matplotlib import pyplot as plt

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)


@ck.command()
@ck.option(
    '--train-data-file', '-trdf', default='data-cafa/train_data.pkl',
    help='Data file with training features')
@ck.option(
    '--test-data-file', '-tsdf', default='data-cafa/predictions.pkl',
    help='Test data file')
@ck.option(
    '--terms-file', '-tf', default='data-cafa/terms.pkl',
    help='Data file with sequences and complete set of annotations')
@ck.option(
    '--diamond-scores-file', '-dsf', default='data-cafa/test_diamond.res',
    help='Diamond output')
@ck.option(
    '--ont', '-o', default='mf',
    help='GO subontology (bp, mf, cc)')
@ck.option(
    '--alpha', '-a', default=50,
    help='Alpha for for combining scores')
def main(train_data_file, test_data_file, terms_file,
         diamond_scores_file, ont, alpha):

    alpha /= 100.0
    go_rels = Ontology('data-cafa/go.obo', with_rels=True)
    terms_df = pd.read_pickle(terms_file)
    terms = terms_df['terms'].values.flatten()
    # terms_dict = {v: i for i, v in enumerate(terms)}

    train_df = pd.read_pickle(train_data_file)
    test_df = pd.read_pickle(test_data_file)
    annotations = train_df['annotations'].values
    annotations = list(map(lambda x: set(x), annotations))
    test_annotations = test_df['annotations'].values
    test_annotations = list(map(lambda x: set(x), test_annotations))

    #### ? notice that @annotations and @test_annotations are used to get IC scores, so we are not allowed to do pre-filtering
    go_rels.calculate_ic(annotations + test_annotations)

    go_set = go_rels.get_namespace_terms(NAMESPACES[ont]) #? consider all the MF or CC or BP

    #### ? filter terms to have only mf ?
    # terms = [t for t in terms if t in go_set]
    # print ('number of terms kept from terms_file {}'.format(len(terms)))

    # Print IC values of terms
    ics = {}
    for term in terms:
        ics[term] = go_rels.get_ic(term)
    ##!! let's save this
    pickle.dump(ics, open("data-cafa/ICsValueTable.pickle","wb"))

    prot_index = {}
    for i, row in enumerate(train_df.itertuples()):
        prot_index[row.proteins] = i


    ####
    # BLAST Similarity (Diamond) #! we can use same call, we have their output
    diamond_scores = {}
    with open(diamond_scores_file) as f:
        for line in f:
            it = line.strip().split()
            if it[0] not in diamond_scores:
                diamond_scores[it[0]] = {}
            diamond_scores[it[0]][it[1]] = float(it[2])

    blast_preds = []
    for i, row in enumerate(test_df.itertuples()):
        annots = {}
        prot_id = row.proteins
        # BlastKNN
        if prot_id in diamond_scores:
            sim_prots = diamond_scores[prot_id]
            allgos = set()
            total_score = 0.0
            for p_id, score in sim_prots.items():
                allgos |= annotations[prot_index[p_id]]
                total_score += score
            allgos = list(sorted(allgos))
            sim = np.zeros(len(allgos), dtype=np.float32)
            for j, go_id in enumerate(allgos):
                s = 0.0
                for p_id, score in sim_prots.items():
                    if go_id in annotations[prot_index[p_id]]:
                        s += score
                sim[j] = s / total_score
            ind = np.argsort(-sim)
            for go_id, score in zip(allgos, sim):
                annots[go_id] = score
        blast_preds.append(annots)

    ####
    # DeepGOPlus

    # go_set = go_rels.get_namespace_terms(NAMESPACES[ont]) #? consider all the MF or CC or BP
    go_set.remove(FUNC_DICT[ont])
    labels = test_df['annotations'].values
    labels = list(map(lambda x: set(filter(lambda y: y in go_set, x)), labels)) ##! filter true labels by @go_set
    print("total labels {}".format(len(go_set)))

    deep_preds = []
    # alphas = {NAMESPACES['mf']: 0.55, NAMESPACES['bp']: 0.59, NAMESPACES['cc']: 0.46}
    for i, row in enumerate(test_df.itertuples()): #! read in prediction of neural net
        annots_dict = {}
        # annots_dict = blast_preds[i].copy() #! copy blast score
        # for go_id in annots_dict: # * set 0 for all @blast_prediction
        #     annots_dict[go_id] = 0 # *= alphas[go_rels.get_namespace(go_id)] #! scale down blast score.
        for j, score in enumerate(row.preds): #! prediction of @test_df
            go_id = terms[j]
            # if go_id not in go_set: #? faster filter of labels because we don't add ancestor anyway
            #     continue
            # score *= 1 - alphas[go_rels.get_namespace(go_id)] # x *= 1-0.5 --> x = x * (1-0.5)
            # if go_id in annots_dict: #? should not need this line??
            #     annots_dict[go_id] += score #! add into blast score
            # else: #! are we going to see error??
            annots_dict[go_id] = score #! replace blast score
        deep_preds.append(annots_dict) #! later on, we use only @deep_preds

    # print('AUTHOR DeepGOPlus')
    # print('MODEL 1')
    # print('KEYWORDS sequence alignment.')
    # for i, row in enumerate(test_df.itertuples()):
    #     prot_id = row.proteins
    #     for go_id, score in deep_preds[i].items():
    #         print(f'{prot_id}\t{go_id}\t{score:.2f}')
    # print('END')
    # return

    # Propagate scores
    # deepgo_preds = []
    # for annots_dict in deep_preds:
    #     annots = {}
    #     for go_id, score in annots_dict.items():
    #         for a_id in go_rels.get_anchestors(go_id):
    #             if a_id in annots:
    #                 annots[a_id] = max(annots[a_id], score)
    #             else:
    #                 annots[a_id] = score
    #     deepgo_preds.append(annots)

    fmax = 0.0
    tmax = 0.0
    precisions = []
    recalls = []
    smin = 1000000.0
    rus = []
    mis = []

    print ('\nontology {}\n'.format(ont))

    ####

    for threshold in np.arange(0.005,.4,.01): # np.arange(0.005,1,.01)
        # threshold = t / 100.0
        print ('\n')
        preds = []
        for i, row in enumerate(test_df.itertuples()):
            annots = set()
            for go_id, score in deep_preds[i].items():
                if go_id not in go_set: #? faster filter of labels because we don't add ancestor anyway
                    continue
                if score >= threshold:
                    annots.add(go_id)

            preds.append(annots)

            ##!! append parent terms or something ??
            # new_annots = set()
            # for go_id in annots:
            #     new_annots |= go_rels.get_anchestors(go_id)
            # preds.append(new_annots)

        # Filter classes
        preds = list(map(lambda x: set(filter(lambda y: y in go_set, x)), preds))

        # print ('see 1 prediction')
        # print (preds[10])
        # print ('see 1 label')
        # print (labels[10])

        fscore, prec, rec, s, ru, mi, fps, fns = evaluate_annotations(go_rels, labels, preds)
        avg_fp = sum(map(lambda x: len(x), fps)) / len(fps)
        avg_ic = sum(map(lambda x: sum(map(lambda go_id: go_rels.get_ic(go_id), x)), fps)) / len(fps)
        print(f'{avg_fp} {avg_ic}')
        precisions.append(prec)
        recalls.append(rec)
        print(f'Fscore: {fscore}, Precision: {prec}, Recall: {rec} S: {s}, RU: {ru}, MI: {mi} threshold: {threshold}')
        if fmax < fscore:
            fmax = fscore
            tmax = threshold
        if smin > s:
            smin = s
    print(f'\nFmax: {fmax:0.3f}, Smin: {smin:0.3f}, threshold: {tmax}')
    precisions = np.array(precisions)
    recalls = np.array(recalls)
    sorted_index = np.argsort(recalls)
    recalls = recalls[sorted_index]
    precisions = precisions[sorted_index]
    aupr = np.trapz(precisions, recalls)
    print(f'AUPR: {aupr:0.3f}')
    plt.figure()
    lw = 2
    plt.plot(recalls, precisions, color='darkorange',
             lw=lw, label=f'AUPR curve (area = {aupr:0.2f})')
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.title('Area Under the Precision-Recall curve')
    plt.legend(loc="lower right")
    plt.savefig(f'aupr_{ont}_{alpha:0.2f}.pdf')
    df = pd.DataFrame({'precisions': precisions, 'recalls': recalls})
    df.to_pickle(f'PR_{ont}_{alpha:0.2f}.pkl')

def compute_roc(labels, preds):
    # Compute ROC curve and ROC area for each class
    fpr, tpr, _ = roc_curve(labels.flatten(), preds.flatten())
    roc_auc = auc(fpr, tpr)
    return roc_auc

def compute_mcc(labels, preds):
    # Compute ROC curve and ROC area for each class
    mcc = matthews_corrcoef(labels.flatten(), preds.flatten())
    return mcc

def evaluate_annotations(go, real_annots, pred_annots):
    total = 0
    p = 0.0
    r = 0.0
    p_total= 0
    ru = 0.0
    mi = 0.0
    fps = []
    fns = []
    for i in range(len(real_annots)):
        if len(real_annots[i]) == 0: ##!! skip if proteins have no labels in this ontology
            continue
        tp = set(real_annots[i]).intersection(set(pred_annots[i]))
        fp = pred_annots[i] - tp #? set operation
        fn = real_annots[i] - tp
        for go_id in fp:
            mi += go.get_ic(go_id)
        for go_id in fn:
            ru += go.get_ic(go_id)
        fps.append(fp)
        fns.append(fn)
        tpn = len(tp)
        fpn = len(fp)
        fnn = len(fn)
        total += 1
        recall = tpn / (1.0 * (tpn + fnn))
        r += recall
        if len(pred_annots[i]) > 0:
            p_total += 1
            precision = tpn / (1.0 * (tpn + fpn))
            p += precision
    ru /= total
    mi /= total
    r /= total
    if p_total > 0:
        p /= p_total
    f = 0.0
    if p + r > 0:
        f = 2 * p * r / (p + r)
    s = math.sqrt(ru * ru + mi * mi)
    print ('total protein count is {}, total with valid prediction {}'.format(total,p_total))
    return f, p, r, s, ru, mi, fps, fns


if __name__ == '__main__':
    # #! debug
    # real_annots = [set([1,2,3]),set([2,3]),set([1]),set([0])]
    # pred_annots = [set([2,3,4,5]),set([]),set([4]),set([])]
    # f, p, r, s, ru, mi, fps, fns = evaluate_annotations(0, real_annots, pred_annots)
    # print (f)
    # exit()
    # #!! end 
    main()

