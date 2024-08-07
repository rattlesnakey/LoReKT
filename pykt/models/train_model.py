from faulthandler import disable
import os, sys
import torch
import torch.nn as nn
from torch.nn.functional import one_hot, binary_cross_entropy, cross_entropy
from torch.nn.utils.clip_grad import clip_grad_norm_
import numpy as np
from .evaluate_model import evaluate
from torch.autograd import Variable, grad
from .atkt import _l2_normalize_adv
from ..utils.utils import debug_print
from pykt.config import que_type_models
import pickle
from torch.utils.data import DataLoader
import itertools
import torch.distributed as dist
from tqdm import tqdm

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")





#softmask
def soft_mask_gradient(model, softmask_for_forward=None, softmask_for_backward=None, model_config=None):

    
    n_layers, n_heads = model_config['n_blocks'], model_config['num_attn_heads']
    head_size = int(model_config['d_model'] / n_heads)

    for layer in range(n_layers):
        
        # attention
        #! head_impt:(512, 32): d_model, head_size
        #! softmask_for_backward['attention'][layer]: [512]
        head_mask, intermediate_mask, output_mask = None, None, None

        # attention mask
        if softmask_for_forward['attention'] != None and softmask_for_backward['attention'] != None:
            head_impt_forward = softmask_for_forward['attention'][layer].unsqueeze(-1).repeat((1, head_size))
            head_impt_backward = softmask_for_backward['attention'][layer].unsqueeze(-1).repeat((1, head_size))
            head_impt_forward = head_impt_forward.flatten()
            head_impt_backward = head_impt_backward.flatten()
            head_impt_backward = 1 - head_impt_backward
            print('mixing attention forward softmask and backward softmask to get attention mask ...')
            
            head_mask = (head_impt_forward + head_impt_backward) / 2
        

        elif softmask_for_forward['attention'] != None and softmask_for_backward['attention'] == None:
            head_impt_forward = softmask_for_forward['attention'][layer].unsqueeze(-1).repeat((1, head_size))
            head_impt = head_impt_forward.flatten()
            head_mask = head_impt
            print('only using forward softmask to get attention mask ...')


        if head_mask != None:
            print('apply attention soft mask to grad ...')
            model.module.model.blocks_2[layer].masked_attn_head.k_linear.weight.grad *= head_mask
            model.module.model.blocks_2[layer].masked_attn_head.v_linear.weight.grad *= head_mask
            model.module.model.blocks_2[layer].masked_attn_head.out_proj.weight.grad *= head_mask
            model.module.model.blocks_2[layer].masked_attn_head.k_linear.bias.grad *= head_mask
            model.module.model.blocks_2[layer].masked_attn_head.v_linear.bias.grad *= head_mask
            model.module.model.blocks_2[layer].masked_attn_head.out_proj.bias.grad *= head_mask
        


        #input mask 
        if softmask_for_forward['input_projection'] != None and softmask_for_backward['input_projection'] != None:
            intermediate_mask_forward = (softmask_for_forward['input_projection'][layer])
            intermediate_mask_backward = (1 - softmask_for_backward['input_projection'][layer])
            print('mixing forward softmask and backward softmask to get input_projection mask ...')
            intermediate_mask =  (intermediate_mask_forward + intermediate_mask_backward) / 2
        
        elif softmask_for_forward['input_projection'] != None and softmask_for_backward['input_projection'] == None:
            intermediate_mask_forward = (softmask_for_forward['input_projection'][layer])
            intermediate_mask = intermediate_mask_forward
            print('only using forward softmask to get input_projection mask ...')
            
        if intermediate_mask != None:
            print('apply input_projection soft mask to grad ...')
            model.module.model.blocks_2[layer].linear1.weight.grad *= intermediate_mask.unsqueeze(1)
            model.module.model.blocks_2[layer].linear1.bias.grad *= intermediate_mask
        


        # output mask 
        if softmask_for_forward['output_projection'] != None and softmask_for_backward['output_projection'] != None:
            output_mask_forward = (softmask_for_forward['output_projection'][layer])
            output_mask_backward = (1 - softmask_for_backward['output_projection'][layer])
            print('mixing forward softmask and backward softmask to get output_projection mask ...')
            output_mask = (output_mask_forward + output_mask_backward) / 2
        

        elif softmask_for_forward['output_projection'] != None and softmask_for_backward['output_projection'] == None:
            output_mask_forward = (softmask_for_forward['output_projection'][layer])
            output_mask = output_mask_forward
            print('only using forward softmask to get output_projection mask ...')
            

       
        if output_mask != None:
            print('apply output_projection soft mask to grad ...')
            model.module.model.blocks_2[layer].linear2.weight.grad *= output_mask.unsqueeze(1)
            model.module.model.blocks_2[layer].linear2.bias.grad *= output_mask


            
         




def cal_loss(model, ys, r, rshft, sm, preloss=[]):
    model_name = model.module.model_name

    if model_name in ["cdkt", "bakt", "bakt_time", "simplekt_sr", "parkt", "mikt", "gpt4kt"]:

        y = torch.masked_select(ys[0], sm)

        t = torch.masked_select(rshft, sm)
        # print(f"y: {y.shape}")
        loss1 = binary_cross_entropy(y.double(), t.double())

        if model.module.emb_type.find("predcurc") != -1:
            if model.module.emb_type.find("his") != -1:
                loss = model.module.l1*loss1+model.module.l2*ys[1]+model.module.l3*ys[2]
            else:
                loss = model.module.l1*loss1+model.module.l2*ys[1]
        elif model.module.emb_type.find("predhis") != -1:
            loss = model.module.l1*loss1+model.module.l2*ys[1]
        elif model.module.emb_type in ["qid_mt"]:
            loss = (1 - model.module.cf_weight)*loss1
            for cl_loss in preloss:
                # print(f"cl_loss:{cl_loss}")
                loss += cl_loss
        # elif model.module.emb_type in ["qid_cl"]:
        #     loss = loss1
        #     for cl_loss in preloss:
        #         # print(f"cl_loss:{cl_loss}")
        #         loss += cl_loss         
        elif model.module.emb_type in ["qid_pvn", "qid_rnn_bi", "qid_rnn_time_augment", "qid_rnn_time_pt", "qid_birnn_time", "qid_birnn_time_pt"] or model.module.emb_type.find("predc") != -1 or model.module.emb_type.find("pt") != -1:
            # print(f"preloss:{preloss}")
            loss = loss1 + preloss
        else:
            loss = loss1

    elif model_name in ["dkt", "dkt_forget", "dkvmn","deep_irt", "kqn", "sakt", "saint", "atkt", "atktfix", "gkt", "skvmn", "hawkes", "gnn4kt"]:
        y = torch.masked_select(ys[0], sm)
        t = torch.masked_select(rshft, sm)
        loss = binary_cross_entropy(y.double(), t.double())
    elif model_name in ["stosakt"]:
        y = torch.masked_select(ys[0], sm)
        t = torch.masked_select(rshft, sm)
        loss = binary_cross_entropy(y.double(), t.double()) + preloss[0]
    elif model_name == "dkt+":
        y_curr = torch.masked_select(ys[1], sm)
        y_next = torch.masked_select(ys[0], sm)
        r_curr = torch.masked_select(r, sm)
        r_next = torch.masked_select(rshft, sm)
        loss = binary_cross_entropy(y_next.double(), r_next.double())

        loss_r = binary_cross_entropy(y_curr.double(), r_curr.double()) # if answered wrong for C in t-1, cur answer for C should be wrong too
        loss_w1 = torch.masked_select(torch.norm(ys[2][:, 1:] - ys[2][:, :-1], p=1, dim=-1), sm[:, 1:])
        loss_w1 = loss_w1.mean() / model.module.num_c
        loss_w2 = torch.masked_select(torch.norm(ys[2][:, 1:] - ys[2][:, :-1], p=2, dim=-1) ** 2, sm[:, 1:])
        loss_w2 = loss_w2.mean() / model.module.num_c

        loss = loss + model.module.lambda_r * loss_r + model.module.lambda_w1 * loss_w1 + model.module.lambda_w2 * loss_w2
    elif model_name in ["akt", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:
        y = torch.masked_select(ys[0], sm)
        t = torch.masked_select(rshft, sm)
        loss = binary_cross_entropy(y.double(), t.double()) + preloss[0]
    elif model_name == "lpkt":
        y = torch.masked_select(ys[0], sm)
        t = torch.masked_select(rshft, sm)
        criterion = nn.BCELoss(reduction='none')        
        loss = criterion(y, t).sum()
    
    return loss



def model_forward(model, data, attn_grads=None, soft_mask=None):
    model_name = model.module.model_name
    # if model_name in ["dkt_forget", "lpkt"]:
    #     q, c, r, qshft, cshft, rshft, m, sm, d, dshft = data
    if model_name in ["dkt_forget", "bakt_time"] or model.module.emb_type.find("time") != -1:
        dcur, dgaps = data
    elif model_name in ["gpt4kt"] and model.module.emb_type.find("pt") != -1:
        dcur, dgaps = data
    else:
        dcur = data
    if model_name in ["dimkt"]:
        q, c, r, t,sd,qd = dcur["qseqs"].to(device), dcur["cseqs"].to(device), dcur["rseqs"].to(device), dcur["tseqs"].to(device),dcur["sdseqs"].to(device),dcur["qdseqs"].to(device)
        qshft, cshft, rshft, tshft,sdshft,qdshft = dcur["shft_qseqs"].to(device), dcur["shft_cseqs"].to(device), dcur["shft_rseqs"].to(device), dcur["shft_tseqs"].to(device),dcur["shft_sdseqs"].to(device),dcur["shft_qdseqs"].to(device)
    else:
        q, c, r = dcur["qseqs"].to(device), dcur["cseqs"].to(device), dcur["rseqs"].to(device)
        if "tseqs" in dcur:
            t = dcur["tseqs"].to(device)
        qshft, cshft, rshft = dcur["shft_qseqs"].to(device), dcur["shft_cseqs"].to(device), dcur["shft_rseqs"].to(device)
        if 'shft_tseqs' in dcur:
            tshft = dcur["shft_tseqs"].to(device)
    
    m, sm = dcur["masks"].to(device), dcur["smasks"].to(device)

    ys, preloss = [], []
    cq = torch.cat((q[:,0:1], qshft), dim=1)
    cc = torch.cat((c[:,0:1], cshft), dim=1)
    cr = torch.cat((r[:,0:1], rshft), dim=1)
    if model_name in ["hawkes"]:
        ct = torch.cat((t[:,0:1], tshft), dim=1)
    elif model_name in ["cdkt"]:
        # is_repeat = dcur["is_repeat"]
        y, y2, y3 = model(dcur, train=True)
        if model.module.emb_type.find("bkt") == -1 and model.module.emb_type.find("addcshft") == -1:
            y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
        # y2 = (y2 * one_hot(cshft.long(), model.module.num_c)).sum(-1)
        ys = [y, y2, y3] # first: yshft
    elif model_name in ["bakt"]:
        y, y2, y3 = model(dcur, train=True, attn_grads=attn_grads)
        ys = [y[:,1:], y2, y3]
    elif model_name in ["gpt4kt"]:
        if model.module.emb_type == "qid":
            y, y2, y3 = model(dcur, train=True, soft_mask=soft_mask)
        elif model.module.emb_type.find("pt") == -1:
            y, y2, y3, preloss = model(dcur, train=True, soft_mask=soft_mask)
        else:
            y, y2, y3, preloss = model(dcur, train=True, dgaps=dgaps, soft_mask=soft_mask)

        ys = [y[:,1:], y2, y3]
        loss = cal_loss(model, ys, r, rshft, sm, preloss)
    elif model_name in ["simplekt_sr", "parkt","mikt"]:
        if model.module.emb_type.find("cl") == -1 and model.module.emb_type.find("mt") == -1 and model.module.emb_type.find("pvn") == -1 and model.module.emb_type.find("bi") == -1 and model.module.emb_type.find("time") == -1:
            y, y2, y3 = model(dcur, train=True)
        
        elif model.module.emb_type.find("time") !=-1:
            if model.module.emb_type.find("augment") !=-1 or model.module.emb_type.find("pt") !=-1 or model.module.emb_type.find("bi") !=-1:
                y, y2, y3, preloss = model(dcur, train=True, dgaps=dgaps)
            else:
                y, y2, y3 = model(dcur, train=True, dgaps=dgaps)
        else:
            y, y2, y3, preloss = model(dcur, train=True)
        ys = [y[:,1:], y2, y3]
    elif model_name in ["bakt_qikt"]:
        loss = model(dcur, train=True, attn_grads=attn_grads)
    elif model_name in ["stosakt"]:
        y, pvn_loss = model(dcur, train=True)
        ys.append(y)
        preloss.append(pvn_loss)
    elif model_name in ["bakt_time"]:
        y, y2, y3 = model(dcur, dgaps, train=True)
        ys = [y[:,1:], y2, y3]
    elif model_name in ["lpkt"]:
        # cat = torch.cat((d["at_seqs"][:,0:1], dshft["at_seqs"]), dim=1)
        cit = torch.cat((dcur["itseqs"][:,0:1], dcur["shft_itseqs"]), dim=1)
    elif model_name in ["dkt"]:
        y = model(c.long(), r.long())
        y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
        ys.append(y) # first: yshft
    elif model_name == "dkt+":
        y = model(c.long(), r.long())
        y_next = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
        y_curr = (y * one_hot(c.long(), model.module.num_c)).sum(-1)
        ys = [y_next, y_curr, y]
    elif model_name in ["dkt_forget"]:
        y = model(c.long(), r.long(), dgaps)
        y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
        ys.append(y)
    elif model_name in ["dkvmn","deep_irt", "skvmn"]:
        y = model(cc.long(), cr.long())
        ys.append(y[:,1:])
    elif model_name in ["kqn", "sakt"]:
        y = model(c.long(), r.long(), cshft.long())
        ys.append(y)
    elif model_name in ["saint"]:
        y = model(cq.long(), cc.long(), r.long())
        ys.append(y[:, 1:])
    elif model_name in ["akt", "akt_vector", "akt_norasch", "akt_mono", "akt_attn", "aktattn_pos", "aktmono_pos", "akt_raschx", "akt_raschy", "aktvec_raschx"]:               
        y, reg_loss = model(cc.long(), cr.long(), cq.long())
        ys.append(y[:,1:])
        preloss.append(reg_loss)
    elif model_name in ["atkt", "atktfix"]:
        y, features = model(c.long(), r.long())
        y = (y * one_hot(cshft.long(), model.module.num_c)).sum(-1)
        loss = cal_loss(model, [y], r, rshft, sm)
        # at
        features_grad = grad(loss, features, retain_graph=True)
        p_adv = torch.FloatTensor(model.module.epsilon * _l2_normalize_adv(features_grad[0].data))
        p_adv = Variable(p_adv).to(device)
        pred_res, _ = model(c.long(), r.long(), p_adv)
        # second loss
        pred_res = (pred_res * one_hot(cshft.long(), model.module.num_c)).sum(-1)
        adv_loss = cal_loss(model, [pred_res], r, rshft, sm)
        loss = loss + model.module.beta * adv_loss
    elif model_name == "gkt":
        y = model(cc.long(), cr.long())
        ys.append(y)  
    elif model_name == "gnn4kt":
        y = model(dcur)
        if model.module.emb_type.find("lstm") != -1:
            y = (y * one_hot(qshft.long(), model.module.num_q)).sum(-1)
            ys.append(y) # first: yshft     
        else:
            ys.append(y[:, 1:]) # first: yshft                 
    # cal loss
    elif model_name == "lpkt":
        # y = model(cq.long(), cr.long(), cat, cit.long())
        y = model(cq.long(), cr.long(), cit.long())
        ys.append(y[:, 1:])  
    elif model_name == "hawkes":
        # ct = torch.cat((dcur["tseqs"][:,0:1], dcur["shft_tseqs"]), dim=1)
        # csm = torch.cat((dcur["smasks"][:,0:1], dcur["smasks"]), dim=1)
        # y = model(cc[0:1,0:5].long(), cq[0:1,0:5].long(), ct[0:1,0:5].long(), cr[0:1,0:5].long(), csm[0:1,0:5].long())
        y = model(cc.long(), cq.long(), ct.long(), cr.long())#, csm.long())
        ys.append(y[:, 1:])
    elif model_name in que_type_models:
        y,loss = model.module.train_one_step(data)
    
    # if model_name in ["simplekt_sr"] and model.module.emb_type.find("mt") == -1:
    #     loss = cal_loss(model, ys, r, rshft, sm, preloss)
    if model_name not in ["atkt", "atktfix","bakt_qikt"]+que_type_models or model_name in ["gnn4kt"]:
        loss = cal_loss(model, ys, r, rshft, sm, preloss)
    return loss

def sample4cl(curtrain, batch_size, i, c0, max_epoch):
    # print(f"curtrain:{type(curtrain)}")
    print(f"curtrain:{len(curtrain)}")
    simple_size = min(1,i*(1-c0)/max_epoch+c0)
    bn = simple_size // 64
    print(f"simple_size:{simple_size}")
    # print(f"simple_size:{int(simple_size*len(curtrain))}")
    # curtrain = curtrain[:2]
    # curtrain = dict(itertools.islice(curtrain.items(),int(simple_size*len(curtrain))))
    # curtrain = curtrain[1885]
    # curtrain = curtrain[:int(simple_size*len(curtrain))]
    # print(f"curtrain:{len(curtrain)}")
    # train_loader = DataLoader(curtrain, batch_size=batch_size)
    return simple_size, bn






def train_model(model, train_loader, valid_loader, num_epochs, opt, ckpt_path, test_loader=None, test_window_loader=None, save_model=False, dataset_name=None, fold=None, curtrain=None,batch_size=None, gradient_accumulation_steps=4.0, softmask_for_forward=None, softmask_for_backward=None, model_config=None, args=None):    
    max_auc, best_epoch = 0, -1
    train_step = 0

    rel = None
    if model.module.model_name == "rkt":
        dpath = data_config["dpath"]
        dataset_name = dpath.split("/")[-1]
        tmp_folds = set(data_config["folds"]) - {fold}
        folds_str = "_" + "_".join([str(_) for _ in tmp_folds])
        if dataset_name in ["algebra2005", "bridge2algebra2006"]:
            fname = "phi_dict" + folds_str + ".pkl"
            rel = pd.read_pickle(os.path.join(dpath, fname))
        else:
            fname = "phi_array" + folds_str + ".pkl" 
            rel = pd.read_pickle(os.path.join(dpath, fname))

    if model.module.model_name=='lpkt':
        scheduler = torch.optim.lr_scheduler.StepLR(opt, 10, gamma=0.5)
    simple_size = 0
    cl_bn = 10000



    for i in range(1, num_epochs + 1):

        print(f"learning rate:{opt.state_dict()['param_groups'][0]['lr']}")

        
        if softmask_for_forward:
            print('using softmask for forward grad training ...')
        else:
            print('not using softmask for forward grad training ...')

        train_loader.sampler.set_epoch(i)
        loss_mean = []
        if model.module.emb_type.find("cl") != -1:
            # a = 1
            if simple_size != 1:
                simple_size, cl_bn = sample4cl(curtrain, batch_size, i, model.module.c0, model.module.max_epoch)
        for j,data in enumerate(tqdm(train_loader, disable=args.local_rank)):
            # if j>=1: break
            # data = data.to(local_rank)
            # j = j.to(local_rank)
            if simple_size != 1 and j > cl_bn:continue
            if model.module.model_name in que_type_models and model.module.model_name not in ["gnn4kt"]:
                model.module.train()
            else:
                model.module.train()
            if model.module.model_name.find("bakt") != -1:
                if j == 0 or model.module.emb_type.find("grad") == -1 and model.module.emb_type != "qid":attn_grads=None
                # if model.module.model_name.find("qikt") == -1:
                #     if j != 0:pre_attn_weights = model.module.attn_weights
                loss = model_forward(model, data, attn_grads)
            else:
  
                loss = model_forward(model, data, i, soft_mask=None)
            
            loss = loss /gradient_accumulation_steps
            

            loss.backward()#compute gradients 
            
            if softmask_for_forward :
                soft_mask_gradient(model=model, softmask_for_forward=softmask_for_forward, softmask_for_backward=None, model_config=model_config)


            

            if (j+1) % gradient_accumulation_steps == 0:  
            # import pdb; pdb.set_trace()
                opt.step()#update model’s parameters   
                opt.zero_grad()
                
            loss_mean.append(loss.detach().cpu().numpy())
            if model.module.model_name == "gkt" and train_step%10==0:
                text = f"Total train step is {train_step}, the loss is {loss.item():.5}"
                debug_print(text = text,fuc_name="train_model")
        if model.module.model_name=='lpkt':
            scheduler.step()#update each epoch
        loss_mean = np.mean(loss_mean)
        
        if model.module.model_name=='rkt':
            auc, acc = evaluate(model, valid_loader, model.module.model_name, rel)
        else:
            auc, acc = evaluate(model, valid_loader, model.module.model_name)
        ### atkt 有diff， 以下代码导致的
        ### auc, acc = round(auc, 4), round(acc, 4)
        if auc > max_auc+1e-3:
            if save_model:

                if dist.get_rank() == 0:

                    # if not args.only_train_learnable_softmask:
                    print(f'save model ...')
                    torch.save(model.module.state_dict(), os.path.join(ckpt_path, model.module.emb_type+"_model.module.ckpt"))
                    if args.save_opt:
                        print(f'saving optimizer ..')
                        torch.save(opt.state_dict(), os.path.join(ckpt_path, "opt.ckpt"))
            max_auc = auc
            best_epoch = i
            testauc, testacc = -1, -1
            window_testauc, window_testacc = -1, -1

            if not save_model:
                if test_loader != None:
                    save_test_path = os.path.join(ckpt_path, model.module.emb_type+"_test_predictions.txt")
                    testauc, testacc = evaluate(model, test_loader, model.module.model_name, save_test_path)
                if test_window_loader != None:
                    save_test_path = os.path.join(ckpt_path, model.module.emb_type+"_test_window_predictions.txt")
                    window_testauc, window_testacc = evaluate(model, test_window_loader, model.module.model_name, save_test_path)
            validauc, validacc = auc, acc
        
        if dist.get_rank() == 0:
            print(f"Epoch: {i}, validauc: {validauc:.4}, validacc: {validacc:.4}, best epoch: {best_epoch}, best auc: {max_auc:.4}, train loss: {loss_mean}, emb_type: {model.module.emb_type}, model: {model.module.model_name}, save_dir: {ckpt_path}")
            print(f"            testauc: {round(testauc,4)}, testacc: {round(testacc,4)}, window_testauc: {round(window_testauc,4)}, window_testacc: {round(window_testacc,4)}")


        if i - best_epoch >= 20:
            break
    
    return testauc, testacc, window_testauc, window_testacc, validauc, validacc, best_epoch
