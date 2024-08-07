import numpy as np
import torch
from torch import nn
from torch.nn.functional import one_hot
from sklearn import metrics
from pykt.config import que_type_models
from ..datasets.lpkt_utils import generate_time2idx
import pandas as pd
import os
import json
#TODO: 会死循环
# from .softmask_utils import impt_norm

device = "cpu" if not torch.cuda.is_available() else "cuda"

#TODO: 添加 norm soft-mask
def impt_norm(impt):
    tanh = torch.nn.Tanh()
    #TODO: 每一层都 mean 和 std normalize 了一下
    for layer in range(impt.size(0)):
        impt[layer] = (impt[layer] - impt[layer].mean()) / impt[
            layer].std()  # 2D, we need to deal with this for each layer
    #TODO: 这边还 tanh + abs 了一下
    impt = tanh(impt).abs()

    return impt

def save_cur_predict_result_emb(dres, q, r, d, t, qemb, qhemb, m, sm, p):
# def save_cur_predict_result(dres, q, r, d, t, m, sm, p):
    # dres, q, r, qshft, rshft, m, sm, y
    results = []
    for i in range(0, t.shape[0]):
        cps = torch.masked_select(p[i], sm[i]).detach().cpu()
        cts = torch.masked_select(t[i], sm[i]).detach().cpu()
    
        cqs = torch.masked_select(q[i], m[i]).detach().cpu()
        crs = torch.masked_select(r[i], m[i]).detach().cpu()

        cds = torch.masked_select(d[i], sm[i]).detach().cpu()

        qs, rs, ts, ps, ds = [], [], [], [], []
        for cq, cr in zip(cqs.int(), crs.int()):
            qs.append(cq.item())
            rs.append(cr.item())
        for ct, cp, cd in zip(cts.int(), cps, cds.int()):
            ts.append(ct.item())
            ps.append(cp.item())
            ds.append(cd.item())
        try:
            auc = metrics.roc_auc_score(
                y_true=np.array(ts), y_score=np.array(ps)
            )
            
        except Exception as e:
            # print(e)
            auc = -1
        # cthr = torch.masked_select(thr[i], sm[i]).detach().cpu().tolist()
        # cphr = torch.masked_select(phr[i], sm[i]).detach().cpu().tolist()
        flag = sm[i]==1
        # sque = que[i][flag].detach().cpu().tolist()
        sq = qemb[i][flag].detach().cpu().tolist()
        sqh = qhemb[i][flag].detach().cpu().tolist()

        prelabels = [1 if p >= 0.5 else 0 for p in ps]
        acc = metrics.accuracy_score(ts, prelabels)
        dres[len(dres)] = [qs, rs, ds, ts, ps, prelabels, auc, acc, sq, sqh]#, cthr, cphr, sque, sqh]
        results.append(str([qs, rs, ds, ts, ps, prelabels, auc, acc, sq, sqh]))#, cthr, cphr, sque, sqh]))
    return "\n".join(results)

def save_cur_predict_result(dres, q, r, d, t, m, sm, p):
    # dres, q, r, qshft, rshft, m, sm, y
    results = []
    for i in range(0, t.shape[0]):
        cps = torch.masked_select(p[i], sm[i]).detach().cpu()
        cts = torch.masked_select(t[i], sm[i]).detach().cpu()
        # print(f"q:{q.shape}")
        # print(f"m:{m.shape}")
        cqs = torch.masked_select(q[i], m[i]).detach().cpu()
        crs = torch.masked_select(r[i], m[i]).detach().cpu()

        cds = torch.masked_select(d[i], sm[i]).detach().cpu()

        qs, rs, ts, ps, ds = [], [], [], [], []
        for cq, cr in zip(cqs.int(), crs.int()):
            qs.append(cq.item())
            rs.append(cr.item())
        for ct, cp, cd in zip(cts.int(), cps, cds.int()):
            ts.append(ct.item())
            ps.append(cp.item())
            ds.append(cd.item())
        try:
            auc = metrics.roc_auc_score(
                y_true=np.array(ts), y_score=np.array(ps)
            )
            
        except Exception as e:
            # print(e)
            auc = -1
        prelabels = [1 if p >= 0.5 else 0 for p in ps]
        acc = metrics.accuracy_score(ts, prelabels)
        dres[len(dres)] = [qs, rs, ds, ts, ps, prelabels, auc, acc]
        results.append(str([qs, rs, ds, ts, ps, prelabels, auc, acc]))
    return "\n".join(results)


def evaluate_testset(model, test_loader, model_name, save_path="", dataset_name="", fold="", attn_cnt_path="", soft_mask_path=None):
    if save_path != "":
        fout = open(save_path, "w", encoding="utf8")

    #TODO: 添加 soft_mask
    if soft_mask_path:
        print(f'loading soft-mask from {soft_mask_path} for evaluating ...')

        ########################################## 这个是之前的非 learnable 的 softmask 的结果 ########################
        #TODO: 所有的 soft_mask 都存在同一个 dir 下面
        #TODO:soft_mask_path 是 save_dir/dataset_name_softmasks
        # inp_proj_soft_mask = torch.Tensor(np.load(os.path.join(soft_mask_path, "intermediate_impt.npy"))).cuda()
        # out_proj_soft_mask = torch.Tensor(np.load(os.path.join(soft_mask_path, "output_impt.npy"))).cuda()
        # attention_soft_mask = torch.Tensor(np.load(os.path.join(soft_mask_path, "head_impt.npy"))).cuda()

        # #TODO: norm soft-mask
        # inp_proj_soft_mask = impt_norm(inp_proj_soft_mask)
        # out_proj_soft_mask = impt_norm(out_proj_soft_mask)
        # attention_soft_mask = impt_norm(attention_soft_mask)
        # soft_mask = {
        #     'input_projection':inp_proj_soft_mask, 
        #     'output_projection':out_proj_soft_mask,
        #     'attention':attention_soft_mask
        # }

        ######################################### 这个是现在的 learnable 的 softmask 的结果 ########################
        soft_mask = torch.load(soft_mask_path, map_location="cuda")

    
    else:
        soft_mask = None



    with torch.no_grad():
        y_trues = []
        y_scores = []
        dres = dict()
        test_mini_index = 0
        dic_emb = {"xemb":{},"yemb":{}}
        dic_emb = dict()
        for data in test_loader:
            # if model_name in ["dkt_forget", "lpkt"]:
            #     q, c, r, qshft, cshft, rshft, m, sm, d, dshft = data
            if model_name in ["dkt_forget", "parkt", "mikt"] and model.emb_type.find("time") != -1:
                dcur, dgaps = data
            elif model_name in ["bakt_time"]:
                dcur, dgaps = data
            elif model_name in ["gpt4kt"] and model.emb_type.find("pt") != -1:
                dcur, dgaps = data
            else:
                dcur = data
            q, c, r = dcur["qseqs"], dcur["cseqs"], dcur["rseqs"]
            qshft, cshft, rshft = dcur["shft_qseqs"], dcur["shft_cseqs"], dcur["shft_rseqs"]
            m, sm = dcur["masks"], dcur["smasks"]
            q, c, r, qshft, cshft, rshft, m, sm = q.to(device), c.to(device), r.to(device), qshft.to(device), cshft.to(device), rshft.to(device), m.to(device), sm.to(device)
            if model.model_name in que_type_models and model.model_name not in ["lpkt", "gnn4kt", "gpt4kt"]:
                model.module.eval()
            else:
                model.eval()

            # print(f"before y: {y.shape}")
            cq = torch.cat((q[:,0:1], qshft), dim=1)
            cc = torch.cat((c[:,0:1], cshft), dim=1)
            cr = torch.cat((r[:,0:1], rshft), dim=1)
            if model_name in ["cdkt"]:
                '''
                y = model(dcur) 
                import pickle
                with open(f"{test_mini_index}_result.pkl",'wb') as f:
                    data = {"y":y,"cshft":cshft,"num_c":model.module.num_c,"rshft":rshft,"qshft":qshft,"sm":sm}
                    pickle.dump(data,f)
                '''
                y, rpreds, qh = model(dcur)
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["bakt_qikt"]:
                y = model(dcur)
            elif model_name in ["bakt_time"]:
                y, qemb, qhemb, dic_emb = model(dcur, dgaps, dic_emb=dic_emb)
                y = y[:,1:]
                qemb = qemb[:,1:,:]
                qhemb = qhemb[:,1:,:]
            elif model_name in ["simplekt_sr", "parkt", "mikt"]:
                if model.module.emb_type.find("time") != -1:
                    y = model(dcur, dgaps=dgaps)
                else:
                    y = model(dcur)
                y = y[:,1:]
            elif model_name in ["stosakt"]:
                y = model(dcur)
            elif model_name in ["bakt"]:
                if model.module.emb_type.find("grad") != -1:
                    save_grad_path = f"./save_attn/{dataset_name}_save_grad_fold_{fold}.npz"
                    save_attn_path = f"./save_attn/{dataset_name}_save_attnweight_fold_{fold}.npz"
                    y = model(dcur, save_attn_path=save_attn_path, save_grad_path=save_grad_path)
                else:
                    y = model(dcur, attn_cnt_path=attn_cnt_path)
                y = y[:,1:]
            elif model_name in ["gpt4kt"]:
                #TODO:不走这个
                if model.emb_type.find("pt") != -1:
                    y = model(dcur, dgaps=dgaps)
                else:
                    #TODO: 这边把 soft_mask 传进去
                    if soft_mask:
                        print(f'eval {dataset_name} using soft-mask ....')
                    else:
                        print(f'eval {dataset_name} not using soft-mask ....')
                    y = model(dcur, soft_mask=soft_mask)
                y = y[:,1:]
                if q.size(1) != 0:
                    c,cshft = q,qshft#question level 
            elif model_name in ["dkt", "dkt+"]:
                y = model(c.long(), r.long())
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["dkt_forget"]:
                y = model(c.long(), r.long(), dgaps)
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["dkvmn","deep_irt", "skvmn","deep_irt"]:
                y = model(cc.long(), cr.long())
                y = y[:,1:]
            elif model_name in ["kqn", "sakt"]:
                y = model(c.long(), r.long(), cshft.long())
            elif model_name == "saint":
                y = model(cq.long(), cc.long(), r.long())
                y = y[:, 1:]
            elif model_name in ["akt", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:                                
                y, reg_loss = model(cc.long(), cr.long(), cq.long())
                y = y[:,1:]
            elif model_name in ["atkt", "atktfix"]:
                y, _ = model(c.long(), r.long())
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name == "gkt":
                y = model(cc.long(), cr.long())
            elif model_name == "gnn4kt":
                y = model(dcur)
                if model.module.emb_type.find("lstm") != -1:
                    y = (y * one_hot(qshft.long(), model.module.num_q)).sum(-1)
                else:
                    y = y[:, 1:]
                c,cshft = q,qshft#question level 
            elif model_name == "lpkt":
                # cat = torch.cat((d["at_seqs"][:,0:1], dshft["at_seqs"]), dim=1).to(device)
                cit = torch.cat((dcur["itseqs"][:,0:1], dcur["shft_itseqs"]), dim=1)
                y = model(cq.long(), cr.long(), cit.long())
                y = y[:,1:]
                c,cshft = q,qshft#question level 
            elif model_name == "hawkes":
                ct = torch.cat((dcur["tseqs"][:,0:1], dcur["shft_tseqs"]), dim=1)
                # csm = torch.cat((dcur["smasks"][:,0:1], dcur["smasks"]), dim=1)
                y = model(cc.long(), cq.long(), ct.long(), cr.long())#, csm.long())
                y = y[:, 1:]
            elif model_name in que_type_models and model_name not in ["lpkt", "gpt4kt", "gnn4kt"]:
                y = model.module.predict_one_step(data)
                c,cshft = q,qshft#question level 
            # print(f"after y: {y.shape}")
            # save predict result
            if save_path != "":
                if model_name not in ["bakt_time"]:
                    result = save_cur_predict_result(dres, c, r, cshft, rshft, m, sm, y)
                else:
                    # print(f"save_path:{save_path}")
                    result = save_cur_predict_result_emb(dres, c, r, cshft, rshft, qemb, qhemb, m, sm, y)
                    # print(f"results:{result}")
                fout.write(result+"\n")

            y = torch.masked_select(y, sm).detach().cpu()
            # print(f"pred_results:{y}")  
            t = torch.masked_select(rshft, sm).detach().cpu()

            y_trues.append(t.numpy())
            y_scores.append(y.numpy())
            test_mini_index+=1
        ts = np.concatenate(y_trues, axis=0)
        ps = np.concatenate(y_scores, axis=0)
        print(f"ts.shape: {ts.shape}, ps.shape: {ps.shape}")
        auc = metrics.roc_auc_score(y_true=ts, y_score=ps)
        prelabels = [1 if p >= 0.5 else 0 for p in ps]
        acc = metrics.accuracy_score(ts, prelabels)
        if model_name in ["bakt_time"]:
            with open(f"./embeddings/{dataset_name}_emb_json.json", "w") as f:
                json.dump(dic_emb, f)
    # if save_path != "":
    #     pd.to_pickle(dres, save_path+".pkl")
    return auc, acc

def evaluate(model, test_loader, model_name, save_path="", dataset_name="", fold="", attn_cnt_path=""):
    if save_path != "":
        fout = open(save_path, "w", encoding="utf8")
    with torch.no_grad():
        y_trues = []
        y_scores = []
        dres = dict()
        test_mini_index = 0
        dic_emb = {"xemb":{},"yemb":{}}
        dic_emb = dict()
        for data in test_loader:
            # if model_name in ["dkt_forget", "lpkt"]:
            #     q, c, r, qshft, cshft, rshft, m, sm, d, dshft = data
            if model_name in ["dkt_forget", "parkt", "mikt"] and model.module.emb_type.find("time") != -1:
                dcur, dgaps = data
            elif model_name in ["bakt_time"]:
                dcur, dgaps = data
            elif model_name in ["gpt4kt"] and model.module.emb_type.find("pt") != -1:
                dcur, dgaps = data
            else:
                dcur = data
            q, c, r = dcur["qseqs"], dcur["cseqs"], dcur["rseqs"]
            qshft, cshft, rshft = dcur["shft_qseqs"], dcur["shft_cseqs"], dcur["shft_rseqs"]
            m, sm = dcur["masks"], dcur["smasks"]
            q, c, r, qshft, cshft, rshft, m, sm = q.to(device), c.to(device), r.to(device), qshft.to(device), cshft.to(device), rshft.to(device), m.to(device), sm.to(device)
            if model.module.model_name in que_type_models and model.module.model_name not in ["lpkt", "gnn4kt", "gpt4kt"]:
                model.module.eval()
            else:
                model.module.eval()

            # print(f"before y: {y.shape}")
            cq = torch.cat((q[:,0:1], qshft), dim=1)
            cc = torch.cat((c[:,0:1], cshft), dim=1)
            cr = torch.cat((r[:,0:1], rshft), dim=1)
            if model_name in ["cdkt"]:
                '''
                y = model(dcur) 
                import pickle
                with open(f"{test_mini_index}_result.pkl",'wb') as f:
                    data = {"y":y,"cshft":cshft,"num_c":model.module.num_c,"rshft":rshft,"qshft":qshft,"sm":sm}
                    pickle.dump(data,f)
                '''
                y, rpreds, qh = model(dcur)
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["bakt_qikt"]:
                y = model(dcur)
            elif model_name in ["bakt_time"]:
                y, qemb, qhemb, dic_emb = model(dcur, dgaps, dic_emb=dic_emb)
                y = y[:,1:]
                qemb = qemb[:,1:,:]
                qhemb = qhemb[:,1:,:]
            elif model_name in ["simplekt_sr", "parkt", "mikt"]:
                if model.module.emb_type.find("time") != -1:
                    y = model(dcur, dgaps=dgaps)
                else:
                    y = model(dcur)
                y = y[:,1:]
            elif model_name in ["stosakt"]:
                y = model(dcur)
            elif model_name in ["bakt"]:
                if model.module.emb_type.find("grad") != -1:
                    save_grad_path = f"./save_attn/{dataset_name}_save_grad_fold_{fold}.npz"
                    save_attn_path = f"./save_attn/{dataset_name}_save_attnweight_fold_{fold}.npz"
                    y = model(dcur, save_attn_path=save_attn_path, save_grad_path=save_grad_path)
                else:
                    y = model(dcur, attn_cnt_path=attn_cnt_path)
                y = y[:,1:]
            elif model_name in ["gpt4kt"]:
                if model.module.emb_type.find("pt") != -1:
                    y = model(dcur, dgaps=dgaps)
                else:
                    y = model(dcur)
                y = y[:,1:]
                if q.size(1) != 0:
                    c,cshft = q,qshft#question level 
            elif model_name in ["dkt", "dkt+"]:
                y = model(c.long(), r.long())
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["dkt_forget"]:
                y = model(c.long(), r.long(), dgaps)
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["dkvmn","deep_irt", "skvmn","deep_irt"]:
                y = model(cc.long(), cr.long())
                y = y[:,1:]
            elif model_name in ["kqn", "sakt"]:
                y = model(c.long(), r.long(), cshft.long())
            elif model_name == "saint":
                y = model(cq.long(), cc.long(), r.long())
                y = y[:, 1:]
            elif model_name in ["akt", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:                                
                y, reg_loss = model(cc.long(), cr.long(), cq.long())
                y = y[:,1:]
            elif model_name in ["atkt", "atktfix"]:
                y, _ = model(c.long(), r.long())
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name == "gkt":
                y = model(cc.long(), cr.long())
            elif model_name == "gnn4kt":
                y = model(dcur)
                if model.module.emb_type.find("lstm") != -1:
                    y = (y * one_hot(qshft.long(), model.module.num_q)).sum(-1)
                else:
                    y = y[:, 1:]
                c,cshft = q,qshft#question level 
            elif model_name == "lpkt":
                # cat = torch.cat((d["at_seqs"][:,0:1], dshft["at_seqs"]), dim=1).to(device)
                cit = torch.cat((dcur["itseqs"][:,0:1], dcur["shft_itseqs"]), dim=1)
                y = model(cq.long(), cr.long(), cit.long())
                y = y[:,1:]
                c,cshft = q,qshft#question level 
            elif model_name == "hawkes":
                ct = torch.cat((dcur["tseqs"][:,0:1], dcur["shft_tseqs"]), dim=1)
                # csm = torch.cat((dcur["smasks"][:,0:1], dcur["smasks"]), dim=1)
                y = model(cc.long(), cq.long(), ct.long(), cr.long())#, csm.long())
                y = y[:, 1:]
            elif model_name in que_type_models and model_name not in ["lpkt", "gpt4kt", "gnn4kt"]:
                y = model.module.predict_one_step(data)
                c,cshft = q,qshft#question level 
            # print(f"after y: {y.shape}")
            # save predict result
            if save_path != "":
                if model_name not in ["bakt_time"]:
                    result = save_cur_predict_result(dres, c, r, cshft, rshft, m, sm, y)
                else:
                    # print(f"save_path:{save_path}")
                    result = save_cur_predict_result_emb(dres, c, r, cshft, rshft, qemb, qhemb, m, sm, y)
                    # print(f"results:{result}")
                fout.write(result+"\n")

            y = torch.masked_select(y, sm).detach().cpu()
            # print(f"pred_results:{y}")  
            t = torch.masked_select(rshft, sm).detach().cpu()

            y_trues.append(t.numpy())
            y_scores.append(y.numpy())
            test_mini_index+=1
        ts = np.concatenate(y_trues, axis=0)
        ps = np.concatenate(y_scores, axis=0)
        print(f"ts.shape: {ts.shape}, ps.shape: {ps.shape}")
        auc = metrics.roc_auc_score(y_true=ts, y_score=ps)
        prelabels = [1 if p >= 0.5 else 0 for p in ps]
        acc = metrics.accuracy_score(ts, prelabels)
        if model_name in ["bakt_time"]:
            with open(f"./embeddings/{dataset_name}_emb_json.json", "w") as f:
                json.dump(dic_emb, f)
    # if save_path != "":
    #     pd.to_pickle(dres, save_path+".pkl")
    return auc, acc

def early_fusion(curhs, model, model_name):
    if model_name in ["dkvmn","skvmn"]:
        p = model.module.p_layer(model.module.dropout_layer(curhs[0]))
        p = torch.sigmoid(p)
        p = p.squeeze(-1)
    elif model_name in ["deep_irt"]:
        p = model.module.p_layer(curhs[0])
        stu_ability = model.module.ability_layer(curhs[0])#equ 12
        que_diff = model.module.diff_layer(curhs[1])#equ 13
        p = torch.sigmoid(3.0*stu_ability-que_diff)#equ 14
        p = p.squeeze(-1)
    elif model_name in ["akt", "bakt", "bakt_time", "simplekt_sr", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:
        output = model.module.out(curhs[0]).squeeze(-1)
        m = nn.Sigmoid()
        p = m(output)
    elif model_name in ["parkt", "mikt"]:
        output = model.module.i2o(curhs[0]).squeeze(-1)
        m = nn.Sigmoid()
        p = m(output)
    elif model_name == "saint":
        p = model.module.out(model.module.dropout(curhs[0]))
        p = torch.sigmoid(p).squeeze(-1)
    elif model_name == "sakt":
        p = torch.sigmoid(model.module.pred(model.module.dropout_layer(curhs[0]))).squeeze(-1)
    elif model_name == "kqn":
        logits = torch.sum(curhs[0] * curhs[1], dim=1) # (batch_size, max_seq_len)
        p = model.module.sigmoid(logits)
    elif model_name == "hawkes":
        p = curhs[0].sigmoid()
    elif model_name == "lpkt":
        p = model.module.sig(model.module.linear_5(torch.cat((curhs[1], curhs[0]), 1))).sum(1) / model.module.d_k
    return p

def late_fusion(dcur, curdf, fusion_type=["mean", "vote", "all"]):
    high, low = [], []
    for pred in curdf["preds"]:
        if pred >= 0.5:
            high.append(pred)
        else:
            low.append(pred)

    if "mean" in fusion_type:
        dcur.setdefault("late_mean", [])
        dcur["late_mean"].append(round(curdf["preds"].mean().astype(float), 4))
    if "vote" in fusion_type:
        dcur.setdefault("late_vote", [])
        correctnum = list(curdf["preds"]>=0.5).count(True)
        late_vote = np.mean(high) if correctnum / len(curdf["preds"]) >= 0.5 else np.mean(low)
        dcur["late_vote"].append(late_vote)
    if "all" in fusion_type:
        dcur.setdefault("late_all", [])
        late_all = np.mean(high) if correctnum == len(curdf["preds"]) else np.mean(low)
        dcur["late_all"].append(late_all)
    return 

def effective_fusion(df, model, model_name, fusion_type):
    dres = dict()
    df = df.groupby("qidx", as_index=True, sort=True)#.mean()

    curhs, curr = [[], []], []
    dcur = {"late_trues": [], "qidxs": [], "questions": [], "concepts": [], "row": [], "concept_preds": []}
    hasearly = ["dkvmn","deep_irt", "skvmn", "kqn", "akt", "bakt", "bakt_time", "simplekt_sr", "saint", "sakt", "hawkes", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx", "lpkt", "parkt", "mikt"]
    for ui in df:
        # 一题一题处理
        curdf = ui[1]
        if model_name in hasearly and model_name not in ["kqn","lpkt","deep_irt"]:
            curhs[0].append(curdf["hidden"].mean().astype(float))
        elif model_name == "kqn":
            curhs[0].append(curdf["ek"].mean().astype(float))
            curhs[1].append(curdf["es"].mean().astype(float))
        elif model_name == "lpkt":
            curhs[0].append(curdf["h"].mean().astype(float))
            curhs[1].append(curdf["e_data"].mean().astype(float))
        elif model_name == "deep_irt":
            curhs[0].append(curdf["h"].mean().astype(float))
            curhs[1].append(curdf["k"].mean().astype(float))
        else:
            # print(f"model: {model_name} has no early fusion res!")
            pass

        curr.append(curdf["response"].mean().astype(int))
        dcur["late_trues"].append(curdf["response"].mean().astype(int))
        dcur["qidxs"].append(ui[0])
        dcur["row"].append(curdf["row"].mean().astype(int))
        dcur["questions"].append(",".join([str(int(s)) for s in curdf["questions"].tolist()]))
        dcur["concepts"].append(",".join([str(int(s)) for s in curdf["concepts"].tolist()]))
        late_fusion(dcur, curdf)
        # save original predres in concepts
        dcur["concept_preds"].append(",".join([str(round(s, 4)) for s in (curdf["preds"].tolist())]))

    for key in dcur:
        dres.setdefault(key, [])
        dres[key].append(np.array(dcur[key]))
    # early fusion
    if "early_fusion" in fusion_type and model_name in hasearly:
        curhs = [torch.tensor(curh).float().to(device) for curh in curhs]
        curr = torch.tensor(curr).long().to(device)
        p = early_fusion(curhs, model, model_name)
        dres.setdefault("early_trues", [])
        dres["early_trues"].append(curr.cpu().numpy())
        dres.setdefault("early_preds", [])
        dres["early_preds"].append(p.cpu().numpy())
    return dres

def group_fusion(dmerge, model, model_name, fusion_type, fout):
    hs, sms, cq, cc, rs, ps, qidxs, rests, orirows = dmerge["hs"], dmerge["sm"], dmerge["cq"], dmerge["cc"], dmerge["cr"], dmerge["y"], dmerge["qidxs"], dmerge["rests"], dmerge["orirow"]
    if cq.shape[1] == 0:
        cq = cc

    hasearly = ["dkvmn","deep_irt", "skvmn", "kqn", "akt", "bakt", "bakt_time", "simplekt_sr", "saint", "sakt", "hawkes", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx", "lpkt", "parkt", "mikt"]
    
    alldfs, drest = [], dict() # not predict infos!
    # print(f"real bz in group fusion: {rs.shape[0]}")
    realbz = rs.shape[0]
    for bz in range(rs.shape[0]):
        cursm = ([0] + sms[bz].cpu().tolist())
        curqidxs = ([-1] + qidxs[bz].cpu().tolist())
        currests = ([-1] + rests[bz].cpu().tolist())
        currows = ([-1] + orirows[bz].cpu().tolist())
        curps = ([-1] + ps[bz].cpu().tolist())
        # print(f"qid: {len(curqidxs)}, select: {len(cursm)}, response: {len(rs[bz].cpu().tolist())}, preds: {len(curps)}")
        df = pd.DataFrame({"qidx": curqidxs, "rest": currests, "row": currows, "select": cursm, 
                "questions": cq[bz].cpu().tolist(), "concepts": cc[bz].cpu().tolist(), "response": rs[bz].cpu().tolist(), "preds": curps})
        if model_name in hasearly and model_name not in ["kqn","lpkt","deep_irt"]:
            df["hidden"] = [np.array(a) for a in hs[0][bz].cpu().tolist()]
        elif model_name == "kqn":
            df["ek"] = [np.array(a) for a in hs[0][bz].cpu().tolist()]
            df["es"] = [np.array(a) for a in hs[1][bz].cpu().tolist()]
        elif model_name == "lpkt":
            # print(f"hidden:{hs[0].shape}")
            df["h"] = [np.array(a) for a in hs[0][bz].cpu().tolist()]
            # print(f"e_data:{hs[1].shape}")
            df["e_data"] = [np.array(a) for a in hs[1][bz].cpu().tolist()]
        elif model_name == "deep_irt":
            df["h"] = [np.array(a) for a in hs[0][bz].cpu().tolist()]
            df["k"] = [np.array(a) for a in hs[1][bz].cpu().tolist()]
        df = df[df["select"] != 0]
        alldfs.append(df)
    
    effective_dfs, rest_start = [], -1
    flag = False
    for i in range(len(alldfs) - 1, -1, -1):
        df = alldfs[i]
        counts = (df["rest"] == 0).value_counts()
        if not flag and False not in counts: # has no question rest > 0
            flag =True
            effective_dfs.append(df)
            rest_start = i + 1
        elif flag:
            effective_dfs.append(df)
    if rest_start == -1:
        rest_start = 0
    # merge rest
    for key in dmerge.keys():
        if key == "hs":
            drest[key] = []
            if model_name in hasearly and model_name not in ["kqn","lpkt","deep_irt"]:
                drest[key] = [dmerge[key][0][rest_start:]]
            elif model_name in ["kqn","lpkt","deep_irt"]:
                drest[key] = [dmerge[key][0][rest_start:], dmerge[key][1][rest_start:]]             
        else:
            drest[key] = dmerge[key][rest_start:] 
    restlen = drest["cr"].shape[0]

    dfs = dict()
    for df in effective_dfs:
        for i, row in df.iterrows():
            for key in row.keys():
                dfs.setdefault(key, [])
                dfs[key].extend([row[key]])
    df = pd.DataFrame(dfs)
    # print(f"real bz: {realbz}, effective_dfs: {len(effective_dfs)}, rest_start: {rest_start}, drestlen: {restlen}, predict infos: {df.shape}")

    if df.shape[0] == 0:
        return {}, drest

    dres = effective_fusion(df, model, model_name, fusion_type)
            
    dfinal = dict()
    for key in dres:
        dfinal[key] = np.concatenate(dres[key], axis=0)
    early = False
    if model_name in hasearly and "early_fusion" in fusion_type:
        early = True
    save_question_res(dfinal, fout, early)
    return dfinal , drest

def save_question_res(dres, fout, early=False):
    # print(f"dres: {dres.keys()}")
    # qidxs, late_trues, late_mean, late_vote, late_all, early_trues, early_preds
    for i in range(0, len(dres["qidxs"])):
        row, qidx, qs, cs, lt, lm, lv, la = dres["row"][i], dres["qidxs"][i], dres["questions"][i], dres["concepts"][i], \
            dres["late_trues"][i], dres["late_mean"][i], dres["late_vote"][i], dres["late_all"][i]
        conceptps = dres["concept_preds"][i]
        curres = [row, qidx, qs, cs, conceptps, lt, lm, lv, la]
        if early:
            et, ep = dres["early_trues"][i], dres["early_preds"][i]
            curres = curres + [et, ep]
        curstr = "\t".join([str(round(s, 4)) if type(s) == type(0.1) or type(s) == np.float32 else str(s) for s in curres])
        fout.write(curstr + "\n")

def evaluate_question(model, test_loader, model_name, fusion_type=["early_fusion", "late_fusion"], save_path="", dataset_name="", fold=""):
    # dkt / dkt+ / dkt_forget / atkt: give past -> predict all. has no early fusion!!!
    # dkvmn / akt / saint: give cur -> predict cur
    # sakt: give past+cur -> predict cur
    # kqn: give past+cur -> predict cur
    hasearly = ["dkvmn","deep_irt", "skvmn", "kqn", "akt", "bakt", "simplekt_sr", "bakt_time", "saint", "sakt", "hawkes", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx", "lpkt", "parkt", "mikt"]
    if save_path != "":
        fout = open(save_path, "w", encoding="utf8")
        if model_name in hasearly:
            fout.write("\t".join(["orirow", "qidx", "questions", "concepts", "concept_preds", "late_trues", "late_mean", "late_vote", "late_all", "early_trues", "early_preds"]) + "\n")
        else:
            fout.write("\t".join(["orirow", "qidx", "questions", "concepts", "concept_preds", "late_trues", "late_mean", "late_vote", "late_all"]) + "\n")
    with torch.no_grad():
        dinfos = dict()
        dhistory = dict()
        history_keys = ["hs", "sm", "cq", "cc", "cr", "y", "qidxs", "rests", "orirow"]
        # for key in history_keys:
        #     dhistory[key] = []
        y_trues, y_scores = [], []
        lenc = 0
        dic_emb = dict()
        for data in test_loader:
            if model_name in ["dkt_forget", "bakt_time"] or model.module.emb_type.find("time") != -1:
                dcurori, dgaps, dqtest = data
            else:
                dcurori, dqtest = data

            q, c, r = dcurori["qseqs"], dcurori["cseqs"], dcurori["rseqs"]
            qshft, cshft, rshft = dcurori["shft_qseqs"], dcurori["shft_cseqs"], dcurori["shft_rseqs"]
            m, sm = dcurori["masks"], dcurori["smasks"]
            q, c, r, qshft, cshft, rshft, m, sm = q.to(device), c.to(device), r.to(device), qshft.to(device), cshft.to(device), rshft.to(device), m.to(device), sm.to(device)
            qidxs, rests, orirow = dqtest["qidxs"], dqtest["rests"], dqtest["orirow"]
            lenc += q.shape[0]
            # print("="*20)
            # print(f"start predict seqlen: {lenc}")
            model.module.eval()

            # print(f"before y: {y.shape}")
            cq = torch.cat((q[:,0:1], qshft), dim=1)
            cc = torch.cat((c[:,0:1], cshft), dim=1)
            cr = torch.cat((r[:,0:1], rshft), dim=1)
            dcur = dict()
            if model_name in ["dkvmn","skvmn"]:
                y, h = model(cc.long(), cr.long(), True)
                y = y[:,1:]
            elif model_name in ["deep_irt"]:
                y, h, k = model(cc.long(), cr.long(), True)
                y = y[:,1:]
                
            elif model_name in ["bakt_time"]:
                y, h, dic_emb,num_c = model(dcurori, dgaps, qtest=True, train=False, dic_emb=dic_emb)
                y = y[:,1:]
                # print(f"dic_emb:{len(dic_emb)}")
                # if len(dic_emb) == num_c:
                #     with open(f"./embeddings/{dataset_name}_emb_json.json", "w") as f:
                #         json.dump(dic_emb, f)
                #         print(f"save embeddings to file!!!")
                #         break
                # start_hemb = torch.tensor([-1] * (h.shape[0] * h.shape[2])).reshape(h.shape[0], 1, h.shape[2]).to(device)
                # print(start_hemb.shape, h.shape)
                # h = torch.cat((start_hemb, h), dim=1) # add the first hidden emb
            elif model_name in ["bakt_qikt"]:
                y = model(dcurori, qtest=True, train=False)
            elif model_name in ["simplekt_sr", "parkt", "mikt"]:
                if model.module.emb_type.find("time") != -1:
                    y, h = model(dcurori, qtest=True, train=False, dgaps=dgaps)
                else:
                    y, h = model(dcurori, qtest=True, train=False)
                y = y[:,1:]
            elif model_name in ["stosakt"]:
                y, seq_mean_emb, seq_cov_emb, mean_sequence_emb, cov_sequence_emb = model(dcurori, qtest=True, train=False)
            elif model_name in ["bakt"]:
                if model.module.emb_type.find("grad") != -1:
                    save_grad_path = f"./save_attn/{dataset_name}_save_grad_fold_{fold}.npz"
                    save_attn_path = f"./save_attn/{dataset_name}_save_attnweight_fold_{fold}.npz"
                    y, h = model(dcurori, qtest=True, train=False, save_attn_path=save_attn_path, save_grad_path=save_grad_path)
                else:
                    y, h = model(dcurori, qtest=True, train=False)
                y = y[:,1:]
            elif model_name in ["akt", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:
                y, reg_loss, h = model(cc.long(), cr.long(), cq.long(), True)
                y = y[:,1:]
            elif model_name == "saint":
                y, h = model(cq.long(), cc.long(), r.long(), True)
                y = y[:,1:]
            elif model_name == "sakt":
                y, h = model(c.long(), r.long(), cshft.long(), True)
                start_hemb = torch.tensor([-1] * (h.shape[0] * h.shape[2])).reshape(h.shape[0], 1, h.shape[2]).to(device)
                # print(start_hemb.shape, h.shape)
                h = torch.cat((start_hemb, h), dim=1) # add the first hidden emb
            elif model_name == "kqn":
                y, ek, es = model(c.long(), r.long(), cshft.long(), True)
                # print(f"ek: {ek.shape},  es: {es.shape}")
                start_hemb = torch.tensor([-1] * (ek.shape[0] * ek.shape[2])).reshape(ek.shape[0], 1, ek.shape[2]).to(device)
                ek = torch.cat((start_hemb, ek), dim=1) # add the first hidden emb
                es = torch.cat((start_hemb, es), dim=1) # add the first hidden emb  
            elif model_name in ["cdkt"]:
                y, _, _ = model(dcurori)#c.long(), r.long(), q.long())
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["dkt", "dkt+"]:
                y, _, _ = model(c.long(), r.long())
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["dkt_forget"]:
                y = model(c.long(), r.long(), dgaps)
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name in ["atkt", "atktfix"]:
                y, _ = model(c.long(), r.long())
                y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
            elif model_name == "gkt":
                y = model(cc.long(), cr.long())
            elif model_name == "hawkes":
                ct = torch.cat((dcurori["tseqs"][:,0:1], dcurori["shft_tseqs"]), dim=1)
                y, h = model(cc.long(), cq.long(), ct.long(), cr.long(), True)
                y = y[:, 1:]
            elif model_name == "lpkt":
                cit = torch.cat((dcurori["itseqs"][:,0:1], dcurori["shft_itseqs"]), dim=1)
                y, h, e_data = model(cq.long(), cr.long(), cit.long(), at_data=None, qtest=True)
                start_hemb = torch.tensor([-1] * (h.shape[0] * h.shape[2])).reshape(h.shape[0], 1, h.shape[2]).to(device) # add the first hidden emb
                h = torch.cat((start_hemb, h), dim=1)
                # e_data = torch.cat((start_hemb, e_data), dim=1)
                y = y[:, 1:]

            concepty = torch.masked_select(y, sm).detach().cpu()
            conceptt = torch.masked_select(rshft, sm).detach().cpu()

            y_trues.append(conceptt.numpy())
            y_scores.append(concepty.numpy())

            # hs, sms, rs, ps, qidxs, model, model_name, fusion_type
            hs = []
            if model_name == "kqn":
                hs = [ek, es]
            elif model_name == "lpkt":
                hs = [h, e_data]
            elif model_name == "deep_irt":
                hs = [h,k]
            elif model_name in hasearly:
                hs = [h]
            dcur["hs"], dcur["sm"], dcur["cq"], dcur["cc"], dcur["cr"], dcur["y"], dcur["qidxs"], dcur["rests"], dcur["orirow"] = hs, sm, cq, cc, cr, y, qidxs, rests, orirow
            # merge history
            dmerge = dict()
            for key in history_keys:
                if len(dhistory) == 0:
                    dmerge[key] = dcur[key]
                else:
                    if key == "hs":
                        dmerge[key] = []
                        if model_name == "kqn":
                            dmerge[key] = [[], []]
                            dmerge[key][0] = torch.cat((dhistory[key][0], dcur[key][0]), dim=0)
                            dmerge[key][1] = torch.cat((dhistory[key][1], dcur[key][1]), dim=0)
                        elif model_name == "lpkt":
                            dmerge[key] = [[], []]
                            dmerge[key][0] = torch.cat((dhistory[key][0], dcur[key][0]), dim=0)
                            dmerge[key][1] = torch.cat((dhistory[key][1], dcur[key][1]), dim=0)
                        elif model_name == "deep_irt":
                            dmerge[key] = [[], []]
                            dmerge[key][0] = torch.cat((dhistory[key][0], dcur[key][0]), dim=0)
                            dmerge[key][1] = torch.cat((dhistory[key][1], dcur[key][1]), dim=0)
                        elif model_name in hasearly:
                            dmerge[key] = [torch.cat((dhistory[key][0], dcur[key][0]), dim=0)]                            
                    else:
                        dmerge[key] = torch.cat((dhistory[key], dcur[key]), dim=0)
                
            dcur, dhistory = group_fusion(dmerge, model, model_name, fusion_type, fout)
            for key in dcur:
                dinfos.setdefault(key, [])
                dinfos[key].append(dcur[key])

            if "early_fusion" in dinfos and "late_fusion" in dinfos:
                assert dinfos["early_trues"][-1].all() == dinfos["late_trues"][-1].all()
            # import sys
            # sys.exit()
        # ori concept eval
        aucs, accs = dict(), dict()
        ts = np.concatenate(y_trues, axis=0)
        ps = np.concatenate(y_scores, axis=0)
        # print(f"ts.shape: {ts.shape}, ps.shape: {ps.shape}")
        auc = metrics.roc_auc_score(y_true=ts, y_score=ps)
        prelabels = [1 if p >= 0.5 else 0 for p in ps]
        acc = metrics.accuracy_score(ts, prelabels)
        aucs["concepts"] = auc
        accs["concepts"] = acc

        # print(f"dinfos: {dinfos.keys()}")
        for key in dinfos:
            if key not in ["late_mean", "late_vote", "late_all", "early_preds"]:
                continue
            ts = np.concatenate(dinfos['late_trues'], axis=0) # early_trues == late_trues
            ps = np.concatenate(dinfos[key], axis=0)
            # print(f"key: {key}, ts.shape: {ts.shape}, ps.shape: {ps.shape}")
            auc = metrics.roc_auc_score(y_true=ts, y_score=ps)
            prelabels = [1 if p >= 0.5 else 0 for p in ps]
            acc = metrics.accuracy_score(ts, prelabels)
            aucs[key] = auc
            accs[key] = acc
        # with open(f"./embeddings/{dataset_name}emb_json.json", "w") as f:
        #     json.dump(dic_emb, f)
    return aucs, accs


def log2(t):
    import math
    return round(math.log(t+1, 2))

def MIKT_calC(row, data_config):
    uid = row["uid"]
    repeated_gap, sequence_gap, past_counts, sequence_it, t_label, pret_label, cit_label = [], [], [], [], [], [],[]
    # default: concepts
    skills = row["concepts"].split(",")
    timestamps = row["timestamps"].split(",")
    dpreskill, dlastskill, dcount = dict(), dict(), dict()
    pret, double_pret = None, None
    cnt = 0
    for idx,(s, t) in enumerate(zip(skills, timestamps)):
        s, t = int(s), int(t)
        if s not in dlastskill or s == -1:
            curRepeatedGap = 0
            curCIt = 0
            dlastskill[s] = -1
        else:
            curRepeatedGap = log2((t - dlastskill[s]) / 1000 / 60) + 1 # minutes
            if dpreskill[s] == -1:
                curCIt = 0.5
            else:
                precit = int((t - dlastskill[s]))/1000
                double_precit = int((t - dpreskill[s]))/1000
                curCIt = round(1 - ((precit + 0.01)/(double_precit + 0.01)),2)
        dpreskill[s] = dlastskill[s]
        dlastskill[s] = t

        repeated_gap.append(curRepeatedGap)
        cit_label.append(curCIt)

        if pret == None or t == -1:
            if t == -1:
                cnt += 1
            curLastGap = 0
            curLastIt = 0
            curPreT = 0
            if idx == 0:
                curLableT = 0
                double_pret = t
            else:
                if cnt == 2:
                    t_label[-1] = 1
                else:
                    curLableT = 0

        else:
            curLastGap = log2((t - pret) / 1000 / 60) + 1
            # curLastIt = min(int((t - pret) / 1000 / 60) + 1,43200)
            curLastIt = int((t - pret)) / 1000
            curPreIt = int((pret - double_pret))/1000
            curPostIt = int((t - double_pret))/1000
            curLableT = round((curPreIt+0.01)/(curPostIt+0.01),2)
            curPreT = round(1 - ((curLastIt + 0.01)/(curPostIt + 0.01)),2)
            double_pret = pret
        pret = t
        sequence_gap.append(curLastGap)
        sequence_it.append(curLastIt)
        t_label.append(curLableT)
        pret_label.append(curPreT)
        
        dcount.setdefault(s, 0)
        ccount = log2(dcount[s])
        ccount = data_config["num_pcount"] - 1 if ccount >= data_config["num_pcount"] else ccount
        past_counts.append(ccount)
        dcount[s] += 1
    t_label = [0]+t_label[2:]+[1]
    pret_label = [0, 0.5]+pret_label[2:]

    return repeated_gap, sequence_gap, past_counts, sequence_it, t_label, pret_label, cit_label

def calC(row, data_config):
    repeated_gap, sequence_gap, past_counts = [], [], []
    uid = row["uid"]
    # default: concepts
    skills = row["concepts"].split(",")
    timestamps = row["timestamps"].split(",")
    dlastskill, dcount = dict(), dict()
    pret = None
    idx = -1
    for s, t in zip(skills, timestamps):
        idx += 1
        s, t = int(s), int(t)
        if s not in dlastskill or s == -1:
            curRepeatedGap = 0
        else:
            curRepeatedGap = log2((t - dlastskill[s]) / 1000 / 60) + 1 # minutes
        dlastskill[s] = t

        repeated_gap.append(curRepeatedGap)
        if pret == None or t == -1:
            curLastGap = 0
        else:
            curLastGap = log2((t - pret) / 1000 / 60) + 1
        pret = t
        sequence_gap.append(curLastGap)

        dcount.setdefault(s, 0)
        ccount = log2(dcount[s])
        ccount = data_config["num_pcount"] - 1 if ccount >= data_config["num_pcount"] else ccount
        past_counts.append(ccount)
        
        dcount[s] += 1
    return repeated_gap, sequence_gap, past_counts    

def MIKT_calC_INDEX(row, data_config):
    repeated_gap, sequence_gap, past_counts, sequence_it, t_label, pret_label, cit_label = [], [], [], [], [], [],[]
    uid = row["uid"]
    # default: concepts
    skills = row["concepts"].split(",")
    # print(f"skills:{skills}")
    timestamps = [i for i in range(len(skills))]
    dpreskill, dlastskill, dcount = dict(), dict(), dict()
    pret, double_pret = None, None
    cnt = 0

    for idx,(s, t) in enumerate(zip(skills, timestamps)):
        s, t = int(s), int(t)
        if s not in dlastskill or s == -1:
            curRepeatedGap = 0
            curCIt = 0
            dlastskill[s] = -1
        else:
            curRepeatedGap = (t - dlastskill[s])# minutes
            if dpreskill[s] == -1:
                # print(f"s:{s}")
                curCIt = 0.5
            else:
                # print(f"s:{s}")
                precit = int((t - dlastskill[s]))
                double_precit = int((t - dpreskill[s]))
                curCIt = round(1 - ((precit + 0.01)/(double_precit + 0.01)),2)
        dpreskill[s] = dlastskill[s]
        dlastskill[s] = t

        curRepeatedGap = data_config["num_rgap"] - 1 if curRepeatedGap >= data_config["num_rgap"] else curRepeatedGap
        repeated_gap.append(curRepeatedGap)
        cit_label.append(curCIt)

        if pret == None or t == -1:
            if t == -1:
                cnt += 1
            curLastGap = 0
            curLastIt = 0
            curPreT = 0
            if idx == 0:
                curLableT = 0
                double_pret = t
            else:
                if cnt == 2:
                    t_label[-1] = 1
                else:
                    curLableT = 0

        else:
            curLastGap = (t - pret) 
            curLastIt = int((t - pret)) 
            curPreIt = int((pret - double_pret))
            curPostIt = int((t - double_pret))
            curLableT = round((curPreIt+0.01)/(curPostIt+0.01),2)
            curPreT = round(1 - ((curLastIt + 0.01)/(curPostIt + 0.01)),2)
            double_pret = pret
        pret = t
        sequence_gap.append(curLastGap)
        sequence_it.append(curLastIt)
        t_label.append(curLableT)
        pret_label.append(curPreT)

        dcount.setdefault(s, 0)
        ccount = dcount[s]
        ccount = data_config["num_pcount"] - 1 if ccount >= data_config["num_pcount"] else ccount
        past_counts.append(ccount)

    t_label = [0]+t_label[2:]+[1]
    pret_label = [0, 0.5]+pret_label[2:]

    return repeated_gap, sequence_gap, past_counts, sequence_it, t_label, pret_label, cit_label       

def get_info_dkt_forget(row, data_config, model_name, dataset_name):
    dforget = dict()
    if model_name not in ["mikt"]:
        rgap, sgap, pcount = calC(row, data_config)

        ## TODO
        dforget["rgaps"], dforget["sgaps"], dforget["pcounts"] = rgap, sgap, pcount
    else:
        if dataset_name not in ["assist2009", "assist2015"]:
            rgap, sgap, pcount, its, tlabel, pretlabel, cit_label = MIKT_calC(row, data_config)
        else:
            rgap, sgap, pcount, its, tlabel, pretlabel, cit_label = MIKT_calC_INDEX(row, data_config)
        dforget["rgaps"], dforget["sgaps"], dforget["pcounts"], dforget["its"], dforget["tlabel"], dforget["pretlabel"], dforget["citlabel"] = rgap, sgap, pcount, its, tlabel, pretlabel, cit_label        
    return dforget

def evaluate_splitpred_question(model, data_config, testf, model_name, save_path="", use_pred=False, train_ratio=0.2, atkt_pad=False):
    if save_path != "":
        fout = open(save_path, "w", encoding="utf8")
    if model_name == "lpkt":
        at2idx, it2idx = generate_time2idx(data_config)
    with torch.no_grad():
        y_trues = []
        y_scores = []
        dres = dict()
        idx = 0
        df = pd.read_csv(testf)
        dcres, dqres = {"trues": [], "preds": []}, {"trues": [], "late_mean": [], "late_vote": [], "late_all": []}
        for i, row in df.iterrows():
            # print(f"idx: {idx}")
            # if idx == 2:
            #     import sys
            #     sys.exit()
            model.module.eval()

            dataset_name = data_config["dpath"].split("/")[-1]
            dforget = dict() if model_name not in ["dkt_forget", "bakt_time", "parkt", "mikt"] else get_info_dkt_forget(row, data_config, model_name, dataset_name)

            concepts, responses = row["concepts"].split(","), row["responses"].split(",")
            ###
            # for AAAI competation
            rs = []
            for item in responses:
                newr = item if item != "-1" else "0" # default -1 to 0
                rs.append(newr)
            responses = rs
            ###
            curl = len(responses)

            # print("="*20)
            is_repeat = ["0"] * curl if "is_repeat" not in row else row["is_repeat"].split(",")
            is_repeat = [int(s) for s in is_repeat]
            questions = [] if "questions" not in row else row["questions"].split(",")
            times = [] if "timestamps" not in row else row["timestamps"].split(",")
            if model_name == "lpkt":
                if times != []:
                    times = [int(x) for x in times]
                    shft_times = [0] + times[:-1]
                    it_times = np.maximum(np.minimum((np.array(times) - np.array(shft_times)) // 60, 43200),-1)
                else:
                    it_times = np.ones(len(concepts)).astype(int)
                it_times = [it2idx.get(str(t)) for t in it_times]
            elif model_name == "dimkt":
                sds = {}
                qds = {}
                dataset_name = data_config["dpath"].split("/")[-1]
                with open(f'/root/autodl-nas/project/pykt_nips2022/data/{dataset_name}/skills_difficult_{model.module.difficult_levels}.csv','r',encoding="UTF8") as f:
                    reader = csv.reader(f)
                    sds_keys = next(reader)
                    sds_vals = next(reader)
                    for i in range(len(sds_keys)):
                        sds[int(sds_keys[i])] = int(sds_vals[i])
                with open(f'/root/autodl-nas/project/pykt_nips2022/data/{dataset_name}/questions_difficult_{model.module.difficult_levels}.csv','r',encoding="UTF8") as f:
                    reader = csv.reader(f)
                    qds_keys = next(reader)
                    qds_vals = next(reader)
                    for i in range(len(qds_keys)):
                        qds[int(qds_keys[i])] = int(qds_vals[i])
                interaction_num = 0
                dqtest = {"qidxs":[],"rests":[], "orirow":[]}
                sds_keys = [int(_) for _ in sds_keys]
                qds_keys = [int(_) for _ in qds_keys]

                seq_sds, seq_qds = [], []
                temp = [int(_) for _ in row["concepts"].split(",")]
                for j in temp:
                    if j == -1:
                        seq_sds.append(-1)
                    elif j not in sds_keys:
                        seq_sds.append(1)
                    else:
                        seq_sds.append(int(sds[j]))

                temp = [int(_) for _ in row["questions"].split(",")]
                for j in temp:
                    if j == -1:
                        seq_qds.append(-1)
                    elif j not in qds_keys:
                        seq_qds.append(1)
                    else:
                        seq_qds.append(int(qds[j]))

            qlen, qtrainlen, ctrainlen = get_cur_teststart(is_repeat, train_ratio)
            # print(f"idx: {idx}, qlen: {qlen}, qtrainlen: {qtrainlen}, ctrainlen: {ctrainlen}")
            # print(concepts)
            # print(responses)
            cq = torch.tensor([int(s) for s in questions]).to(device)
            cc = torch.tensor([int(s) for s in concepts]).to(device)
            cr = torch.tensor([int(s) for s in responses]).to(device)
            ct = torch.tensor([int(s) for s in times]).to(device)
            dtotal = {"cq": cq, "cc": cc, "cr": cr, "ct": ct}
            if model_name == "lpkt":
                cit = torch.tensor([int(s) for s in it_times]).to(device)
                dtotal["cit"] = cit
            elif model_name == "dimkt":
                # print(f"cq:{cq}")
                # print(f"seq_sds:{seq_sds}")
                csd = torch.tensor(seq_sds).to(device)
                cqd = torch.tensor(seq_qds).to(device)
                dtotal["csd"] = csd
                dtotal["cqd"] = cqd
            # print(f"cc: {cc[0:ctrainlen]}")
            curcin, currin = cc[0:ctrainlen].unsqueeze(0), cr[0:ctrainlen].unsqueeze(0)
            # print(f"cin6: {curcin}")
            # print(f"rin6: {currin}")
            curqin = cq[0:ctrainlen].unsqueeze(0) if cq.shape[0] > 0 else cq
            curtin = ct[0:ctrainlen].unsqueeze(0) if ct.shape[0] > 0 else ct
            if model_name == "lpkt":
                curitin = cit[0:ctrainlen].unsqueeze(0) if cit.shape[0] > 0 else cit
            elif model_name == "dimkt":
                cursdin= csd[0:ctrainlen].unsqueeze(0) if csd.shape[0] > 0 else csd
                curqdin = cqd[0:ctrainlen].unsqueeze(0) if cqd.shape[0] > 0 else cqd
            dcur = {"curqin": curqin, "curcin": curcin, "currin": currin, "curtin": curtin}
            if model_name == "lpkt":
                dcur["curitin"] = curitin
            elif model_name == "dimkt":
                dcur["cursdin"] = cursdin
                dcur["curqdin"] = curqdin
            curdforget = dict()
            for key in dforget:
                dforget[key] = torch.tensor(dforget[key]).to(device)
                curdforget[key] = dforget[key][0:ctrainlen].unsqueeze(0)
            # print(f"curcin: {curcin}")
            t = ctrainlen

            ### 如果不用预测结果，可以从这里并行了
            
            if not use_pred:
                uid, end = row["uid"], curl
                qidx = qtrainlen
                # qidxs, ctrues, cpreds = predict_each_group2(curdforget, dforget, is_repeat, qidx, uid, idx, curqin, curcin, currin, model_name, model, t, cq, cc, cr, end, fout, atkt_pad)
                # qidxs, ctrues, cpreds = predict_each_group2(curdforget, dforget, is_repeat, qidx, uid, idx, dcur, model_name, model, t, dtotal, end, fout, atkt_pad)
                qidxs, ctrues, cpreds = predict_each_group2(dtotal, dcur, dforget, curdforget, is_repeat, qidx, uid, idx, model_name, model, t, end, fout, atkt_pad)
                # 计算
                save_currow_question_res(idx, dcres, dqres, qidxs, ctrues, cpreds, uid, fout)
            else:
                qidx = qtrainlen
                while t < curl:
                    rtmp = [t]
                    for k in range(t+1, curl):
                        if is_repeat[k] != 0:
                            rtmp.append(k)
                        else:
                            break

                    end = rtmp[-1]+1
                    uid = row["uid"]
                    if model_name == "lpkt":
                        curqin, curcin, currin, curtin, curitin, curdforget, ctrues, cpreds = predict_each_group(dtotal, dcur, dforget, curdforget, is_repeat, qidx, uid, idx, model_name, model, t, end, fout, atkt_pad)
                        dcur = {"curqin": curqin, "curcin": curcin, "currin": currin, "curtin": curtin, "curitin": curitin}
                    elif model_name == "dimkt":
                        curqin, curcin, currin, curtin, cursdin, curqdin, ctrues, cpreds = predict_each_group(dtotal, dcur, dforget, curdforget, is_repeat, qidx, uid, idx, model_name, model, t, end, fout, atkt_pad)
                        dcur = {"curqin": curqin, "curcin": curcin, "currin": currin, "curtin": curtin, "cursdin": cursdin, "curqdin":curqdin}
                    else:
                        curqin, curcin, currin, curtin, curdforget, ctrues, cpreds = predict_each_group(dtotal, dcur, dforget, curdforget, is_repeat, qidx, uid, idx, model_name, model, t, end, fout, atkt_pad)
                        dcur = {"curqin": curqin, "curcin": curcin, "currin": currin, "curtin": curtin}
                    late_mean, late_vote, late_all = save_each_question_res(dcres, dqres, ctrues, cpreds)    
   
                    fout.write("\t".join([str(idx), str(uid), str(qidx), str(late_mean), str(late_vote), str(late_all)]) + "\n")      
                    t = end
                    qidx += 1
            idx += 1

        try: 
            dfinal = cal_predres(dcres, dqres)
            for key in dfinal:
                fout.write(key + "\t" + str(dfinal[key]) + "\n")
        except:
            print(f"can't output auc and accuracy!")
            dfinal = dict()
    return dfinal

def get_cur_teststart(is_repeat, train_ratio):
    curl = len(is_repeat)
    # print(is_repeat)
    qlen = is_repeat.count(0)
    qtrainlen = int(qlen * train_ratio)
    qtrainlen = 1 if qtrainlen == 0 else qtrainlen
    qtrainlen = qtrainlen - 1 if qtrainlen == qlen else qtrainlen
    # get real concept len
    ctrainlen, qidx = 0, 0
    i = 0
    while i < curl:
        if is_repeat[i] == 0:
            qidx += 1
        # print(f"i: {i}, curl: {curl}, qidx: {qidx}, qtrainlen: {qtrainlen}")
        # qtrainlen = 7 if qlen>7 else qtrainlen
        if qidx == qtrainlen:
            break
        i += 1
    for j in range(i+1, curl):
        if is_repeat[j] == 0:
            ctrainlen = j
            break
    return qlen, qtrainlen, ctrainlen

# def predict_each_group(curdforget, dforget, is_repeat, qidx, uid, idx, curqin, curcin, currin, model_name, model, t, cq, cc, cr, end, fout, atkt_pad=False, maxlen=200):
def predict_each_group(dtotal, dcur, dforget, curdforget, is_repeat, qidx, uid, idx, model_name, model, t, end, fout, atkt_pad=False, maxlen=200):
    """use the predict result as next question input
    """
    curqin, curcin, currin, curtin = dcur["curqin"], dcur["curcin"], dcur["currin"], dcur["curtin"]
    # print(f"cin8:{curcin}")
    # print(f"rin8:{currin}")
    cq, cc, cr, ct = dtotal["cq"], dtotal["cc"], dtotal["cr"], dtotal["ct"]
    if model_name == "lpkt":
        curitin = dcur["curitin"]
        cit = dtotal["cit"]
    if model_name == "dimkt":
        cursdin = dcur["cursdin"]
        curqdin = dcur["curqdin"]
        csd = dtotal["csd"]
        cqd = dtotal["cqd"]

    nextcin, nextrin = curcin, currin
    import copy
    nextdforget = copy.deepcopy(curdforget)
    ctrues, cpreds = [], []
    for k in range(t, end):
        qin, cin, rin, tin = curqin, curcin, currin, curtin
        # print(f"cin9:{cin}")
        # print(f"rin9:{rin}")
        if model_name == "lpkt":
            itin = curitin
        if model_name == "dimkt":
            sdin = cursdin 
            qdin = curqdin 
        # 输入长度大于200时，截断
        # print("cin: ", cin)
        start = 0
        cinlen = cin.shape[1]
        if cinlen >= maxlen - 1:
            start = cinlen - maxlen + 1
        
        cin, rin = cin[:,start:], rin[:,start:]
        # print(f"cin10:{cin}")
        # print(f"rin10:{rin}")

        if cq.shape[0] > 0:
            qin = qin[:, start:]
        if ct.shape[0] > 0:
            tin = tin[:, start:]
        if model_name == "lpkt":
            itin = itin[:, start:]
        if model_name == "dimkt":
            sdin = sdin[:, start:]
            qdin = qdin[:, start:]
        # print(f"start: {start}, cin: {cin.shape}")
        cout, true = cc.long()[k], cr.long()[k] # 当前预测的是第k个
        qout = None if cq.shape[0] == 0 else cq.long()[k]
        tout = None if ct.shape[0] == 0 else ct.long()[k]
        
        if model_name == "lpkt":
            itout = None if cit.shape[0] == 0 else cit.long()[k]
        if model_name == "dimkt":
            sdout = None if csd.shape[0] == 0 else csd.long()[k]
            qdout = None if cqd.shape[0] == 0 else cqd.long()[k]
        if model_name in ["dkt", "dkt+"]:
            y = model(cin.long(), rin.long())
            # print(y)
            pred = y[0][-1][cout.item()]
        if model_name in ["dkt_forget", "bakt_time","parkt","mikt"]:
            din = dict()
            for key in curdforget:
                din[key] = curdforget[key][:,start:]
            dcur = dict()
            for key in dforget:
                curd = torch.tensor([[dforget[key][k]]]).long().to(device)
                dcur[key] = torch.cat((din[key][:,1:], curd), axis=1)
            dgaps = dict()
            for key in din:
                dgaps[key] = din[key]
            for key in dcur:
                dgaps["shft_"+key] = dcur[key]
        if model_name in ["cdkt"]: ## need change!
            # create input
            dcurinfos = {"qseqs": qin, "cseqs": cin, "rseqs": rin}
            y, _, _ = model(dcurinfos)
            pred = y[0][-1][cout.item()]
        elif model_name in ["dkt", "dkt+"]:
            y = model(cin.long(), rin.long())
            # print(y)
            pred = y[0][-1][cout.item()]
        elif model_name == "dkt_forget":
            # y = model(cin.long(), rin.long(), din, dcur)
            y = model(cin.long(), rin.long(), dgaps)
            pred = y[0][-1][cout.item()]
        elif model_name in ["kqn", "sakt"]:
            curc = torch.tensor([[cout.item()]]).to(device)
            cshft = torch.cat((cin[:,1:],curc), axis=1)
            y = model(cin.long(), rin.long(), cshft.long())
            pred = y[0][-1]
        elif model_name == "saint":
            #### 输入有question！
            if qout != None:
                curq = torch.tensor([[qout.item()]]).to(device)
                qin = torch.cat((qin, curq), axis=1)
            curc = torch.tensor([[cout.item()]]).to(device)
            cin = torch.cat((cin, curc), axis=1)
            
            y = model(qin.long(), cin.long(), rin.long())
            pred = y[0][-1]
        elif model_name in ["atkt", "atktfix"]:
            if atkt_pad == True:
                oricinlen = cin.shape[1]
                padlen = maxlen-1-oricinlen
                # print(f"padlen: {padlen}, cin: {cin.shape}")
                pad = torch.tensor([0]*(padlen)).unsqueeze(0).to(device)
                # curc = torch.tensor([[cout.item()]]).to(device)
                # cshft = torch.cat((cin[:,1:],curc), axis=1)
                cin = torch.cat((cin, pad), axis=1)
                rin = torch.cat((rin, pad), axis=1)
            y, _ = model(cin.long(), rin.long())
            # print(f"y: {y}")
            if atkt_pad == True:
                # print(f"use idx: {oricinlen-1}")
                pred = y[0][oricinlen-1][cout.item()]
            else:
                pred = y[0][-1][cout.item()]
        elif model_name in ["dkvmn","deep_irt", "skvmn"]:
            curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[true.item()]]).to(device)
            cin, rin = torch.cat((cin, curc), axis=1), torch.cat((rin, curr), axis=1)
            # print(f"cin: {cin.shape}, curc: {curc.shape}")
            # 应该用预测的r更新memory value，但是这里一个知识点一个知识点预测，所以curr不起作用！
            y = model(cin.long(), rin.long())
            pred = y[0][-1]
        elif model_name in ["akt", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:  
            #### 输入有question！     
            if qout != None:
                curq = torch.tensor([[qout.item()]]).to(device)
                qin = torch.cat((qin, curq), axis=1)
            # curr不起作用！当前预测不用curr，实际用的历史的也不一定是true，用的是rin，可能是预测，可能是历史
            curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[1]]).to(device)
            cin, rin = torch.cat((cin, curc), axis=1), torch.cat((rin, curr), axis=1)

            y, reg_loss = model(cin.long(), rin.long(), qin.long())
            pred = y[0][-1]
        elif model_name in ["bakt_time", "parkt", "mikt"]:
           if qout != None:
               curq = torch.tensor([[qout.item()]]).to(device)
               qinshft = torch.cat((qin[:,1:], curq), axis=1)
           else:
               qin = torch.tensor([[]]).to(device)
               qinshft = torch.tensor([[]]).to(device)
           curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[1]]).to(device)
           cinshft, rinshft = torch.cat((cin[:,1:], curc), axis=1), torch.cat((rin[:,1:], curr), axis=1)
           dcurinfos = {"qseqs": qin, "cseqs": cin, "rseqs": rin, "shft_qseqs": qinshft, "shft_cseqs": cinshft, "shft_rseqs": rinshft}
           
           y = model(dcurinfos, dgaps=dgaps)
           pred = y[0][-1]
        elif model_name in ["bakt","simplekt_sr"]:
           if qout != None:
               curq = torch.tensor([[qout.item()]]).to(device)
               qinshft = torch.cat((qin[:,1:], curq), axis=1)
           else:
               qin = torch.tensor([[]]).to(device)
               qinshft = torch.tensor([[]]).to(device)
           curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[1]]).to(device)
           cinshft, rinshft = torch.cat((cin[:,1:], curc), axis=1), torch.cat((rin[:,1:], curr), axis=1)
           dcurinfos = {"qseqs": qin, "cseqs": cin, "rseqs": rin, "shft_qseqs": qinshft, "shft_cseqs": cinshft, "shft_rseqs": rinshft}
           
           y = model(dcurinfos)
           pred = y[0][-1]
        elif model_name == "lpkt":
            if itout != None:
                curit = torch.tensor([[itout.item()]]).to(device)
                itin = torch.cat((itin, curit), axis=1)
            curq, curr = torch.tensor([[qout.item()]]).to(device), torch.tensor([[1]]).to(device)
            # curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[true.item()]]).to(device)
            qin, rin = torch.cat((qin, curq), axis=1), torch.cat((rin, curr), axis=1)
            y = model(qin.long(), rin.long(), itin.long())
            # print(f"pred: {y}")
            # label = [1 if x >= 0.5 else 0 for x in y[0]]
            # print(f"pred_labels: {label}")
            pred = y[0][-1]
        elif model_name == "dimkt":
            if sdout != None and qdout != None:
                cursd = torch.tensor([[sdout.item()]]).to(device)
                # sdin = torch.cat((sdin, cursd), axis=1)
                curqd = torch.tensor([[qdout.item()]]).to(device)
                # qdin = torch.cat((qdin, curqd), axis=1)
            curq, curc, curr = torch.tensor([[qout.item()]]).to(device), torch.tensor([[cout.item()]]).to(device), torch.tensor([[1]]).to(device)
            # qin, cin, rin = torch.cat((qin, curq), axis=1), torch.cat((cin, curc), axis=1), torch.cat((rin, curr), axis=1)
            qinshft, cinshft, rinshft, sdinshft, qdinshft = torch.cat((qin[:,1:], curq), axis=1), torch.cat((cin[:,1:], curc), axis=1), torch.cat((rin[:,1:], curr), axis=1), torch.cat((sdin[:,1:], cursd), axis=1), torch.cat((qdin[:,1:], curqd), axis=1)
            # qinshft, cinshft, rinshft, sdinshft, qdinshft = qin[:,1:], cin[:,1:], rin, sdin[:,1:], qdin[:,1:]
            # print(f"qin:{qin.shape}, qinshft:{qinshft.shape}")
            y = model(qin.long(), cin.long(), sdin.long(), qdin.long(), rin.long(), qinshft.long(), cinshft.long(), sdinshft.long(), qdinshft.long())
            pred = y[0][-1]
        elif model_name == "gkt":
            curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[1]]).to(device)
            cin, rin = torch.cat((cin, curc), axis=1), torch.cat((rin, curr), axis=1)
            y = model(cin.long(), rin.long())
            # print(f"y.shape is {y.shape},cin shape is {cin.shape}")
            pred = y[0][-1]
        elif model_name == "hawkes":
            curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[1]]).to(device)
            if tout != None:
                curt = torch.tensor([[tout.item()]]).to(device)
                tin = torch.cat((tin, curt), axis=1)
            else:
                tin = torch.tensor([[]]).to(device)
            if qout != None:
                curq = torch.tensor([[qout.item()]]).to(device)
                qin = torch.cat((qin, curq), axis=1)
            curc, curr = torch.tensor([[cout.item()]]).to(device), torch.tensor([[1]]).to(device)
            cin, rin = torch.cat((cin, curc), axis=1), torch.cat((rin, curr), axis=1)
            #print(f"cin: {cin.shape}, qin: {qin.shape}, tin: {tin.shape}, rin: {rin.shape}")
            y = model(cin.long(), qin.long(), tin.long(), rin.long())
            pred = y[0][-1]
        
        predl = 1 if pred.item() >= 0.5 else 0
        cpred = torch.tensor([[predl]]).to(device)

        nextqin = cq[0:k+1].unsqueeze(0) if cq.shape[0] > 0 else qin
        nexttin = ct[0:k+1].unsqueeze(0) if ct.shape[0] > 0 else tin
        nextcin = cc[0:k+1].unsqueeze(0)
        nextrin = torch.cat((nextrin, cpred), axis=1)### change!!
        if model_name == "lpkt":
            nexttin = ct[0:k+1].unsqueeze(0) if ct.shape[0] > 0 else tin
            nextitin = cit[0:k+1].unsqueeze(0) if cit.shape[0] > 0 else itin
        if model_name == "dimkt":
            nextsdin = csd[0:k+1].unsqueeze(0) if csd.shape[0] > 0 else sdin
            nextqdin = cqd[0:k+1].unsqueeze(0) if cqd.shape[0] > 0 else qdin
        # update nextdforget
        if model_name in ["dkt_forget", "bakt_time", "mikt"]:
            for key in nextdforget:
                curd = torch.tensor([[dforget[key][k]]]).long().to(device)
                nextdforget[key] = torch.cat((nextdforget[key], curd), axis=1)
        # print(f"bz: {bz}, t: {t}, pred: {pred}, true: {true}")

        # save pred res
        ctrues.append(true.item())
        cpreds.append(pred.item())

        # output
        clist, rlist = cin.squeeze(0).long().tolist()[0:k], rin.squeeze(0).long().tolist()[0:k]
        # print("\t".join([str(idx), str(uid), str(k), str(qidx), str(is_repeat[t:end]), str(len(clist)), str(clist), str(rlist), str(cout.item()), str(true.item()), str(pred.item()), str(predl)]))
        fout.write("\t".join([str(idx), str(uid), str(k), str(qidx), str(is_repeat[t:end]), str(len(clist)), str(clist), str(rlist), str(cout.item()), str(true.item()), str(pred.item()), str(predl)]) + "\n")
    # nextcin, nextrin = nextcin.unsqueeze(0), nextrin.unsqueeze(0)
    if model_name == "lpkt":
        return nextqin, nextcin, nextrin, nexttin, nextitin, nextdforget, ctrues, cpreds
    elif model_name == "dimkt":
        return nextqin, nextcin, nextrin, nexttin, nextsdin, nextqdin, ctrues, cpreds
    else:
        return nextqin, nextcin, nextrin, nexttin, nextdforget, ctrues, cpreds

def save_each_question_res(dcres, dqres, ctrues, cpreds):
    # save res
    high, low = [], []
    for true, pred in zip(ctrues, cpreds):
        dcres["trues"].append(true)
        dcres["preds"].append(pred)
        if pred >= 0.5:
            high.append(pred)
        else:
            low.append(pred)
    cpreds = np.array(cpreds)
    late_mean = np.mean(cpreds)
    correctnum = list(cpreds>=0.5).count(True)
    late_vote = np.mean(high) if correctnum / len(cpreds) >= 0.5 else np.mean(low)
    late_all = np.mean(high) if correctnum == len(cpreds) else np.mean(low)
    assert len(set(ctrues)) == 1
    dqres["trues"].append(dcres["trues"][-1])
    dqres["late_mean"].append(late_mean)
    dqres["late_vote"].append(late_vote)
    dqres["late_all"].append(late_all)
    return late_mean, late_vote, late_all

def cal_predres(dcres, dqres):
    dres = dict()#{"concept": [], "late_mean": [], "late_vote": [], "late_all": []}

    ctrues, cpreds = np.array(dcres["trues"]), np.array(dcres["preds"])
    # print(f"key: concepts, ts.shape: {ctrues.shape}, ps.shape: {cpreds.shape}")
    auc = metrics.roc_auc_score(y_true=ctrues, y_score=cpreds)
    prelabels = [1 if p >= 0.5 else 0 for p in cpreds]
    acc = metrics.accuracy_score(ctrues, prelabels)

    dres["concepts"] = [len(cpreds), auc, acc]

    qtrues = np.array(dqres["trues"])
    for key in dqres:
        if key == "trues":
            continue
        preds = np.array(dqres[key])
        # print(f"key: {key}, ts.shape: {qtrues.shape}, ps.shape: {preds.shape}")
        auc = metrics.roc_auc_score(y_true=qtrues, y_score=preds)
        prelabels = [1 if p >= 0.5 else 0 for p in preds]
        acc = metrics.accuracy_score(qtrues, prelabels)
        dres[key] = [len(preds), auc, acc]
    return dres

def prepare_data(model_name, is_repeat, qidx, dcur, curdforget, dtotal, dforget, t, end, maxlen=200):
    curqin, curcin, currin, curtin = dcur["curqin"], dcur["curcin"], dcur["currin"], dcur["curtin"]
    cq, cc, cr, ct = dtotal["cq"], dtotal["cc"], dtotal["cr"], dtotal["ct"]
    dqshfts, dcshfts, drshfts, dtshfts, dds, ddshfts = [], [], [], [], dict(), dict()
    dqs, dcs, drs, dts = [], [], [], []
    if model_name == "lpkt":
        curitin = dcur["curitin"]
        cit = dtotal["cit"]
        dits, ditshfts = [], []
    elif model_name == "dimkt":
        cursdin, curqdin = dcur["cursdin"],dcur["curqdin"]
        csd, cqd = dtotal["csd"], dtotal["cqd"]
        dsds, dsdshfts, dqds, dqdshfts = [], [], [], []
    qidxs = []
    qstart = qidx-1
    for k in range(t, end):
        if is_repeat[k] == 0:
            qstart += 1
            qidxs.append(qstart)
        else:
            qidxs.append(qstart)
        # get start
        start = 0
        cinlen = curcin.shape[1]
        if cinlen >= maxlen - 1:
            start = cinlen - maxlen + 1

        curc, curr = cc.long()[k], cr.long()[k]
        curc, curr = torch.tensor([[curc.item()]]).to(device), torch.tensor([[curr.item()]]).to(device)
        dcs.append(curcin[:, start:])
        drs.append(currin[:, start:])

        curc, curr = torch.cat((curcin[:, start+1:], curc), axis=1), torch.cat((currin[:, start+1:], curr), axis=1)
        dcshfts.append(curc)
        drshfts.append(curr)
        if cq.shape[0] > 0:
            curq = cq.long()[k]
            curq = torch.tensor([[curq.item()]]).to(device)

            dqs.append(curqin[:, start:])
            curq = torch.cat((curqin[:, start+1:], curq), axis=1)
            dqshfts.append(curq)
        if ct.shape[0] > 0:
            curt = ct.long()[k]
            curt = torch.tensor([[curt.item()]]).to(device)

            dts.append(curtin[:, start:])
            curt = torch.cat((curtin[:, start+1:], curt), axis=1)
            dtshfts.append(curt)
        if model_name == "lpkt":
            if cit.shape[0] > 0:
                curit = cit.long()[k]
                curit = torch.tensor([[curit.item()]]).to(device)

                dits.append(curitin[:, start:])
                curit = torch.cat((curitin[:, start+1:], curit), axis=1)
                ditshfts.append(curit)
        elif model_name == "dimkt":
            cursd = csd.long()[k]
            cursd = torch.tensor([[cursd.item()]]).to(device)
            curqd = cqd.long()[k]
            curqd = torch.tensor([[curqd.item()]]).to(device)

            dsds.append(cursdin[:, start:])
            cursd = torch.cat((cursdin[:, start+1:], cursd), axis=1)
            dsdshfts.append(cursd)

            dqds.append(curqdin[:, start:])
            curqd = torch.cat((curqdin[:, start+1:], curqd), axis=1)
            dqdshfts.append(curqd)     

        d, dshft = dict(), dict()
        if model_name in ["dkt_forget", "bakt_time", "parkt", "mikt"]:
            # print(f"curdforget:{curdforget}")
            for key in curdforget:
                d[key] = curdforget[key][:,start:]
                dds.setdefault(key, [])
                dds[key].append(d[key])
            for key in dforget:
                curd = torch.tensor([[dforget[key][k]]]).long().to(device)
                dshft[key] = torch.cat((d[key][:,1:], curd), axis=1)
                ddshfts.setdefault(key, [])
                ddshfts[key].append(dshft[key])
        
    finalcs, finalrs = torch.cat(dcs, axis=0), torch.cat(drs, axis=0)
    finalqs, finalqshfts = torch.tensor([]), torch.tensor([])
    finalts, finaltshfts = torch.tensor([]), torch.tensor([]) 
    if cq.shape[0] > 0:
        finalqs = torch.cat(dqs, axis=0)
        finalqshfts = torch.cat(dqshfts, axis=0)
    if ct.shape[0] > 0:
        finalts = torch.cat(dts, axis=0)
        finaltshfts = torch.cat(dtshfts, axis=0)
    finalcshfts, finalrshfts = torch.cat(dcshfts, axis=0), torch.cat(drshfts, axis=0)
    finald, finaldshft = dict(), dict()
    for key in dds:
        finald[key] = torch.cat(dds[key], axis=0)
        finaldshft[key] = torch.cat(ddshfts[key], axis=0)
    # print(f"qidx: {len(qidxs)}, finalqs: {finalqs.shape}, finalcs: {finalcs.shape}, finalrs: {finalrs.shape}")
    # print(f"qidx: {len(qidxs)}, finalqshfts: {finalqshfts.shape}, finalcshfts: {finalcshfts.shape}, finalrshfts: {finalrshfts.shape}")
    if model_name == "lpkt":
        finalits, finalitshfts = torch.tensor([]), torch.tensor([])
        if cit.shape[0] > 0:
            finalits = torch.cat(dits, axis=0)
            finalitshfts = torch.cat(ditshfts, axis=0)
    elif model_name == "dimkt":
        finalsds, finalsdshfts, finalqds, finalqdshfts = torch.tensor([]), torch.tensor([]), torch.tensor([]), torch.tensor([])
        finalsds = torch.cat(dsds, axis=0)
        finalsdshfts = torch.cat(dsdshfts, axis=0)
        finalqds = torch.cat(dqds, axis=0)
        finalqdshfts = torch.cat(dqdshfts, axis=0)


    if model_name == "lpkt":
        return qidxs, finalqs, finalcs, finalrs, finalts, finalits, finalqshfts, finalcshfts, finalrshfts, finaltshfts, finalitshfts, finald, finaldshft
    elif model_name == "dimkt":
        return qidxs, finalqs, finalcs, finalrs, finalts, finalqshfts, finalcshfts, finalrshfts, finaltshfts, finalsds, finalsdshfts, finalqds, finalqdshfts, finald, finaldshft
    else:
        return qidxs, finalqs, finalcs, finalrs, finalts, finalqshfts, finalcshfts, finalrshfts, finaltshfts, finald, finaldshft

# def predict_each_group2(curdforget, dforget, is_repeat, qidx, uid, idx, curqin, curcin, currin, model_name, model, t, cq, cc, cr, end, fout, atkt_pad=False, maxlen=200):
def predict_each_group2(dtotal, dcur, dforget, curdforget, is_repeat, qidx, uid, idx, model_name, model, t, end, fout, atkt_pad=False, maxlen=200):
    """not use the predict result
    """
    curqin, curcin, currin, curtin = dcur["curqin"], dcur["curcin"], dcur["currin"], dcur["curtin"]
    cq, cc, cr, ct = dtotal["cq"], dtotal["cc"], dtotal["cr"], dtotal["ct"]
    if model_name == "lpkt":
        cit = dtotal["cit"]
    elif model_name == "dimkt":
        csd = dtotal["csd"]
        cqd = dtotal["cqd"]
    nextcin, nextrin = curcin, currin
    import copy
    nextdforget = copy.deepcopy(curdforget)
    ctrues, cpreds = [], []
    # 以下这些用的是同一个历史,可以并行
    # 不用预测结果
    if model_name == "lpkt":
        qidxs, finalqs, finalcs, finalrs, finalts, finalits, finalqshfts, finalcshfts, finalrshfts, finaltshfts, finalitshfts, finald, finaldshft = prepare_data(model_name, is_repeat, qidx, dcur, curdforget, dtotal, dforget, t, end)
    elif model_name == "dimkt":
        qidxs, finalqs, finalcs, finalrs, finalts, finalqshfts, finalcshfts, finalrshfts, finaltshfts, finalsds, finalsdshfts, finalqds, finalqdshfts, finald, finaldshft = prepare_data(model_name, is_repeat, qidx, dcur, curdforget, dtotal, dforget, t, end)
    else:
        qidxs, finalqs, finalcs, finalrs, finalts, finalqshfts, finalcshfts, finalrshfts, finaltshfts, finald, finaldshft = prepare_data(model_name, is_repeat, qidx, dcur, curdforget, dtotal, dforget, t, end)
    bidx, bz = 0, 128
    # print(f"finalcs:{finalcs.shape}")
    while bidx < finalcs.shape[0]:
        curc, curr = finalcs[bidx: bidx+bz], finalrs[bidx: bidx+bz]
        curcshft, currshft = finalcshfts[bidx: bidx+bz], finalrshfts[bidx: bidx+bz]
        curqidxs = qidxs[bidx: bidx+bz]
        curq, curqshft = torch.tensor([[]]), torch.tensor([[]])
        if finalqs.shape[0] > 0:
            curq = finalqs[bidx: bidx+bz]
            curqshft = finalqshfts[bidx: bidx+bz]
        curt, curtshft = torch.tensor([[]]), torch.tensor([[]])
        if finalts.shape[0] > 0:
            curt = finalts[bidx: bidx+bz]
            curtshft = finaltshfts[bidx: bidx+bz]
        curd, curdshft = dict(), dict()
        if model_name in ["dkt_forget", "bakt_time", "parkt", "mikt"]:
            for key in finald:
                curd[key] = finald[key][bidx: bidx+bz]
                curdshft[key] = finaldshft[key][bidx: bidx+bz]
        if model_name == "lpkt":
            curit = finalits[bidx: bidx+bz]
            curitshft = finalitshfts[bidx: bidx+bz]
        if model_name == "dimkt":
            cursd = finalsds[bidx: bidx+bz]
            cursdshft = finalsdshfts[bidx: bidx+bz]     
            curqd = finalqds[bidx: bidx+bz]
            curqdshft = finalqdshfts[bidx: bidx+bz]             
        ## start predict
        ccq = torch.cat((curq[:,0:1], curqshft), dim=1)
        ccc = torch.cat((curc[:,0:1], curcshft), dim=1)
        ccr = torch.cat((curr[:,0:1], currshft), dim=1)
        cct = torch.cat((curt[:,0:1], curtshft), dim=1)
        if model_name in ["dkt_forget", "bakt_time", "parkt", "mikt"]:
            dgaps = dict()
            for key in curd:
                dgaps[key] = curd[key]
            for key in curdshft:
                dgaps["shft_"+key] = curdshft[key]
            # print(f"dgaps:{dgaps}")
        if model_name in ["cdkt"]:
            # y = model(curc.long(), curr.long(), curq.long())
            # y = (y * one_hot(curcshft.long(), model.module.num_c)).sum(-1)
            # create input
            dcurinfos = {"qseqs": curq, "cseqs": curc, "rseqs": curr}
            y, _, _ = model(dcurinfos)
            y = (y * one_hot(curcshft.long(), model.module.num_c)).sum(-1)
        elif model_name in ["dkt", "dkt+"]:
            y = model(curc.long(), curr.long())
            y = (y * one_hot(curcshft.long(), model.module.num_c)).sum(-1)
        elif model_name in ["dkt_forget"]:
            y = model(curc.long(), curr.long(), dgaps)
            # y = model(curc.long(), curr.long(), curd, curdshft)
            y = (y * one_hot(curcshft.long(), model.module.num_c)).sum(-1)
        elif model_name in ["dkvmn","deep_irt", "skvmn"]:
            y = model(ccc.long(), ccr.long())
            y = y[:,1:]
        elif model_name in ["kqn", "sakt"]:
            y = model(curc.long(), curr.long(), curcshft.long())
        elif model_name == "saint":
            y = model(ccq.long(), ccc.long(), curr.long())
            y = y[:, 1:]
        elif model_name in ["akt", "cakt", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:                                
            y, reg_loss = model(ccc.long(), ccr.long(), ccq.long())
            y = y[:,1:]
        elif model_name in ["atkt", "atktfix"]:
            # print(f"atkt_pad: {atkt_pad}")
            if atkt_pad == True:
                oricurclen = curc.shape[1]
                padlen = maxlen-1-oricurclen
                # print(f"padlen: {padlen}, curc: {curc.shape}")
                pad = torch.tensor([0]*padlen).unsqueeze(0).expand(curc.shape[0], padlen).to(device)
                curc = torch.cat((curc, pad), axis=1)
                curr = torch.cat((curr, pad), axis=1)
                curcshft = torch.cat((curcshft, pad), axis=1)
            y, _ = model(curc.long(), curr.long())
            y = (y * one_hot(curcshft.long(), model.module.num_c)).sum(-1)
        elif model_name == "lpkt":
            ccit = torch.cat((curit[:,0:1], curitshft), dim=1)
            y = model(ccq.long(), ccr.long(), ccit.long())
            y = y[:, 1:]
        elif model_name in ["bakt_time", "parkt", "mikt"]:
            dcurinfos = {"qseqs": curq, "cseqs": curc, "rseqs": curr,
                       "shft_qseqs":curqshft,"shft_cseqs":curcshft,"shft_rseqs":currshft}
            # print(f"finald: {finald.keys()}")
            # print(f"dgaps: {dgaps.keys()}")
            y = model(dcurinfos, dgaps=dgaps)
            y = y[:,1:]
        elif model_name in ["bakt","simplekt_sr"]:
            dcurinfos = {"qseqs": curq, "cseqs": curc, "rseqs": curr,
                       "shft_qseqs":curqshft,"shft_cseqs":curcshft,"shft_rseqs":currshft}
            # print(f"finald: {finald.keys()}")
            # print(f"dgaps: {dgaps.keys()}")
            y = model(dcurinfos)
            y = y[:,1:]
        elif model_name == "gkt":
            y = model(ccc.long(), ccr.long())
            # print(f"y: {y}")
            # y = y[:, t-1:t]
        elif model_name == "hawkes":
            y = model(ccc.long(), ccq.long(), cct.long(), ccr.long())
            pred = y[0][-1]
        if model_name in ["atkt", "atktfix"] and atkt_pad == True:
            # print(f"use idx: {oricurclen-1}")
            pred = y[:, oricurclen-1].tolist()
            # assert ccr[:, t] == curcshft[:, t-1]
            true = currshft[:, oricurclen-1].tolist()
            # print(true)
            # true = curcshft[:, t-1].tolist()
        else:
            pred = y[:, -1].tolist()
            true = ccr[:, -1].tolist()
        
        # print(f"pred: {len(pred)}, true: {true}")

        # save pred res
        ctrues.extend(true)
        cpreds.extend(pred)

        # output
        
        for i in range(0, curc.shape[0]):
            clist, rlist = curc[i].long().tolist()[0:t], curr[i].long().tolist()[0:t]
            cshftlist, rshftlist = curcshft[i].long().tolist()[0:t], currshft[i].long().tolist()[0:t]
            qidx = curqidxs[i]
            predl = 1 if pred[i] >= 0.5 else 0
            # print("\t".join([str(idx), str(uid), str(bidx+i), str(qidx), str(len(clist)), str(clist), str(rlist), str(cshftlist), str(rshftlist), str(true[i]), str(pred[i]), str(predl)]))
            fout.write("\t".join([str(idx), str(uid), str(bidx+i), str(qidx), str(len(clist)), str(clist), str(rlist), str(cshftlist), str(rshftlist), str(true[i]), str(pred[i]), str(predl)]) + "\n")

        bidx += bz
    return qidxs, ctrues, cpreds

def save_currow_question_res(idx, dcres, dqres, qidxs, ctrues, cpreds, uid, fout):
    # save res
    dqidx = dict()
    # dhigh, dlow = dict(), dict()
    for i in range(0, len(qidxs)):
        true, pred = ctrues[i], cpreds[i]
        qidx = qidxs[i]
        dqidx.setdefault(qidx, {"trues": [], "preds": []})
        dqidx[qidx]["trues"].append(true)
        dqidx[qidx]["preds"].append(pred)

    for qidx in dqidx:
        ctrues, cpreds = dqidx[qidx]["trues"], dqidx[qidx]["preds"]
        late_mean, late_vote, late_all = save_each_question_res(dcres, dqres, ctrues, cpreds)
        # print("\t".join([str(idx), str(uid), str(qidx), str(late_mean), str(late_vote), str(late_all)]))
        fout.write("\t".join([str(idx), str(uid), str(qidx), str(late_mean), str(late_vote), str(late_all)]) + "\n")

