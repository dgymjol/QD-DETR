import torch
from torch.utils.data import Dataset
import numpy as np
from tqdm import tqdm
import random
import logging
from os.path import join, exists
from utils.basic_utils import load_jsonl, l2_normalize_np_array
from utils.tensor_utils import pad_sequences_1d
from qd_detr.span_utils import span_xx_to_cxw
import CLIP
import clip

import spacy

logger = logging.getLogger(__name__)


class StartEndDataset(Dataset):
    Q_FEAT_TYPES = ["pooler_output", "last_hidden_state"]
    """One line in data loaded from data_path."
    {
      "qid": 7803,
      "query": "Man in gray top walks from outside to inside.",
      "duration": 150,
      "vid": "RoripwjYFp8_360.0_510.0",
      "relevant_clip_ids": [13, 14, 15, 16, 17],
      "relevant_windows": [[26, 36]]
    }
    """

    def __init__(self, dset_name, data_path, v_feat_dirs, q_feat_dir,
                 q_feat_type="last_hidden_state",
                 max_q_l=32, max_v_l=75, data_ratio=1.0, ctx_mode="video", use_cliptext=None, text_ratio=0.5,
                 normalize_v=True, normalize_t=True, load_labels=True,
                 clip_len=2, max_windows=5, span_loss_type="l1", txt_drop_ratio=0,
                 dset_domain=None,
                 m_classes = None):
        self.dset_name = dset_name
        self.data_path = data_path
        self.data_ratio = data_ratio
        self.v_feat_dirs = v_feat_dirs \
            if isinstance(v_feat_dirs, list) else [v_feat_dirs]
        self.q_feat_dir = q_feat_dir
        self.q_feat_type = q_feat_type
        self.max_q_l = max_q_l
        self.max_v_l = max_v_l
        self.ctx_mode = ctx_mode
        self.use_tef = "tef" in ctx_mode
        self.use_cliptext = use_cliptext
        self.use_video = "video" in ctx_mode
        self.normalize_t = normalize_t
        self.normalize_v = normalize_v
        self.load_labels = load_labels
        self.clip_len = clip_len
        self.max_windows = max_windows  # maximum number of windows to use as labels
        self.span_loss_type = span_loss_type
        self.txt_drop_ratio = txt_drop_ratio
        if "val" in data_path or "test" in data_path:
            assert txt_drop_ratio == 0

        # checks
        assert q_feat_type in self.Q_FEAT_TYPES

        # data
        self.data = self.load_data()
        
        # load specific domain data for tvsum dataset
        if self.dset_name == 'tvsum':
            target_domain = dset_domain
            assert target_domain in ["BK", "BT", "DS", "FM", "GA", "MS", "PK", "PR", "VT", "VU"]

            new_data = []
            for d in self.data:
                if target_domain == d['domain']:
                    new_data.append(d)
            self.data = new_data

        if self.use_cliptext:
            print(f"++++++++++++++++++++++ CLIP {self.use_cliptext} +++++++++++++++++++++++++++++++++")

            clip_type, self.text_type = self.use_cliptext.split(' ')

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.clip_model, _ = CLIP.load(clip_type, device=self.device)

            self.nlp = spacy.load('en_core_web_lg')

            self.text_ratio = text_ratio

        if m_classes is not None:
            self.m_vals = [int(v) for v in m_classes[1:-1].split(',')]
        else:
            self.m_vals=None
        

    def load_data(self):
        datalist = load_jsonl(self.data_path)
        if self.data_ratio != 1:
            n_examples = int(len(datalist) * self.data_ratio)
            datalist = datalist[:n_examples]
            logger.info("Using {}% of the data: {} examples"
                        .format(self.data_ratio * 100, n_examples))
        return datalist

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        meta = self.data[index]

        model_inputs = dict()
        if self.use_cliptext is None:
            model_inputs["query_feat"] = self._get_query_feat_by_qid(meta["qid"])  # (Dq, ) or (Lq, Dq)
        else:
            if self.text_type == 'org_hidden_state':
                # sentence -> last hidden state
                model_inputs["query_feat"] = self._get_clip_text_feat(meta["query"])  # (Dq, ) or (Lq, Dq)

            elif self.text_type == 'global_local_features':
                # sentence -> final feature (global)
                # noun -> final feature (local)
                # final = global + local
                model_inputs["query_feat"] = self._get_global_local_features(meta["query"], self.text_ratio)

            elif self.text_type == 'hidden_features':
                # sentence -> last hidden state
                # sen + noun -> final feature
                # final = last hidden state + final feature
                model_inputs["query_feat"] = self._get_hidden_features(meta["query"], self.text_ratio)

            elif self.text_type == 'global_local_hidden_state':
                # sentence -> last hidden state (global)
                # noun -> last hidden state (local)
                # final = local + global
                model_inputs["query_feat"] = self._get_global_local_hidden_states(meta["query"], self.text_ratio)

            elif self.text_type == 'only_local_hidden_state':
                # noun -> last hidden state (local)
                model_inputs["query_feat"] = self._get_only_noun_hidden_states(meta["query"])

                
        if self.use_video:
            model_inputs["video_feat"] = self._get_video_feat_by_vid(meta["vid"])  # (Lv, Dv)
            ctx_l = len(model_inputs["video_feat"])
        else:
            ctx_l = self.max_v_l

        if self.use_tef:
            tef_st = torch.arange(0, ctx_l, 1.0) / ctx_l
            tef_ed = tef_st + 1.0 / ctx_l
            tef = torch.stack([tef_st, tef_ed], dim=1)  # (Lv, 2)
            if self.use_video:
                model_inputs["video_feat"] = torch.cat(
                    [model_inputs["video_feat"], tef], dim=1)  # (Lv, Dv+2)
            else:
                model_inputs["video_feat"] = tef

        if self.load_labels:
            if self.dset_name == 'tvsum': 
                model_inputs["span_labels"] = torch.tensor([[0., 0.]])
                meta_label = meta['label']
                model_inputs["saliency_pos_labels"], model_inputs["saliency_neg_labels"], model_inputs["saliency_all_labels"] = \
                            self.get_saliency_labels_all_tvsum(meta_label, ctx_l)
            else:
                model_inputs["span_labels"], lengths = self.get_span_labels(meta["relevant_windows"], ctx_l)  # (#windows, 2)
                if "subs_train" not in self.data_path:
                    model_inputs["saliency_pos_labels"], model_inputs["saliency_neg_labels"], model_inputs["saliency_all_labels"] = \
                        self.get_saliency_labels_all(meta["relevant_clip_ids"], meta["saliency_scores"], ctx_l)
                else:
                    model_inputs["saliency_pos_labels"], model_inputs["saliency_neg_labels"], model_inputs["saliency_all_labels"] = \
                        self.get_saliency_labels_sub_as_query(meta["relevant_windows"][0], ctx_l)  # only one gt

        moment_class = []
        if self.m_vals is not None:
            for l in lengths:
                for m_cls, m_val in enumerate(self.m_vals):
                    if l <= m_val:
                        moment_class.append(m_cls)
                        break
            model_inputs["moment_class"] = torch.tensor(moment_class)
            
            assert len(model_inputs["moment_class"]) == len(lengths)
                    
        return dict(meta=meta, model_inputs=model_inputs)

    def get_saliency_labels_sub_as_query(self, gt_window, ctx_l, max_n=2):
        gt_st = int(gt_window[0] / self.clip_len)
        gt_ed = max(0, min(int(gt_window[1] / self.clip_len), ctx_l) - 1)
        if gt_st > gt_ed:
            gt_st = gt_ed

        if gt_st != gt_ed:
            pos_clip_indices = random.sample(range(gt_st, gt_ed+1), k=max_n)
        else:
            pos_clip_indices = [gt_st, gt_st]

        neg_pool = list(range(0, gt_st)) + list(range(gt_ed+1, ctx_l))
        neg_clip_indices = random.sample(neg_pool, k=max_n)
        # return pos_clip_indices, neg_clip_indices
        
        score_array = np.zeros(ctx_l)
        score_array[gt_st:gt_ed+1] = 1

        return pos_clip_indices, neg_clip_indices, score_array
        

    def get_saliency_labels(self, rel_clip_ids, scores, ctx_l, max_n=1, add_easy_negative=True):
        """Sum the scores from the three annotations, then take the two clips with the
        maximum scores as positive, and two with the minimum scores as negative.
        Args:
            rel_clip_ids: list(int), list of relevant clip ids
            scores: list([anno1_score, anno2_score, anno3_score]),
            ctx_l: int
            max_n: int, #clips to use as positive and negative, for easy and hard negative, respectively.
            add_easy_negative: bool, if True, sample eay negative outside the relevant_clip_ids.
        """
        # indices inside rel_clip_ids
        scores = np.array(scores)  # (#rel_clips, 3)
        agg_scores = np.sum(scores, 1)  # (#rel_clips, )
        sort_indices = np.argsort(agg_scores)  # increasing

        # indices in the whole video
        # the min(_, ctx_l-1) here is incorrect, but should not cause
        # much troubles since this should be rarely used.
        hard_pos_clip_indices = [min(rel_clip_ids[idx], ctx_l-1) for idx in sort_indices[-max_n:]]
        hard_neg_clip_indices = [min(rel_clip_ids[idx], ctx_l-1) for idx in sort_indices[:max_n]]
        easy_pos_clip_indices = []
        easy_neg_clip_indices = []
        if add_easy_negative:
            easy_neg_pool = list(set(range(ctx_l)) - set(rel_clip_ids))
            if len(easy_neg_pool) >= max_n:
                easy_pos_clip_indices = random.sample(rel_clip_ids, k=max_n)
                easy_neg_clip_indices = random.sample(easy_neg_pool, k=max_n)
            else:  # copy the hard ones
                easy_pos_clip_indices = hard_pos_clip_indices
                easy_neg_clip_indices = hard_neg_clip_indices

        pos_clip_indices = hard_pos_clip_indices + easy_pos_clip_indices
        neg_clip_indices = hard_neg_clip_indices + easy_neg_clip_indices
        return pos_clip_indices, neg_clip_indices

    def get_saliency_labels_all(self, rel_clip_ids, scores, ctx_l, max_n=1, add_easy_negative=True):
        """Sum the scores from the three annotations, then take the two clips with the
        maximum scores as positive, and two with the minimum scores as negative.
        Args:
            rel_clip_ids: list(int), list of relevant clip ids
            scores: list([anno1_score, anno2_score, anno3_score]),
            ctx_l: int
            max_n: int, #clips to use as positive and negative, for easy and hard negative, respectively.
            add_easy_negative: bool, if True, sample eay negative outside the relevant_clip_ids.
        """
        # indices inside rel_clip_ids
        scores = np.array(scores)  # (#rel_clips, 3)
        agg_scores = np.sum(scores, 1)  # (#rel_clips, )
        sort_indices = np.argsort(agg_scores)  # increasing

        # score_array = [min(agg_scores[idx], ctx_l-1) for idx in range(ctx_l)]
        score_array = np.zeros(ctx_l)
        for idx in range(len(rel_clip_ids)):
            if rel_clip_ids[idx] >= ctx_l:
                score_array_new = np.zeros(ctx_l + 1)
                score_array_new[:ctx_l] = score_array
                score_array = score_array_new
            # if rel_clip_ids[idx] == ctx_l:
            #     print(rel_clip_ids[idx], ctx_l)
            score_array[rel_clip_ids[idx]] = agg_scores[idx]

        # indices in the whole video
        # the min(_, ctx_l-1) here is incorrect, but should not cause
        # much troubles since this should be rarely used.
        hard_pos_clip_indices = [min(rel_clip_ids[idx], ctx_l-1) for idx in sort_indices[-max_n:]]
        hard_neg_clip_indices = [min(rel_clip_ids[idx], ctx_l-1) for idx in sort_indices[:max_n]]
        easy_pos_clip_indices = []
        easy_neg_clip_indices = []
        if add_easy_negative:
            easy_neg_pool = list(set(range(ctx_l)) - set(rel_clip_ids))
            if len(easy_neg_pool) >= max_n:
                easy_pos_clip_indices = random.sample(rel_clip_ids, k=max_n)
                easy_neg_clip_indices = random.sample(easy_neg_pool, k=max_n)
            else:  # copy the hard ones
                easy_pos_clip_indices = hard_pos_clip_indices
                easy_neg_clip_indices = hard_neg_clip_indices

        pos_clip_indices = hard_pos_clip_indices + easy_pos_clip_indices
        neg_clip_indices = hard_neg_clip_indices + easy_neg_clip_indices
        return pos_clip_indices, neg_clip_indices, score_array

    def get_saliency_labels_all_tvsum(self, labels, ctx_l, max_n=1, add_easy_negative=False):
        
        agg_scores = np.sum(labels - np.ones_like(labels), axis=-1)[:ctx_l] # start from 1, so minus 1
        score_array = agg_scores / 80 * 12
        sort_indices = np.argsort(agg_scores)  # increasing

        hard_pos_clip_indices = [min(idx, ctx_l-1) for idx in sort_indices[-max_n:]]
        hard_neg_clip_indices = [min(idx, ctx_l-1) for idx in sort_indices[:max_n]]
        easy_pos_clip_indices = []
        easy_neg_clip_indices = []
        if add_easy_negative:
            easy_neg_pool = list(set(range(ctx_l)))
            if len(easy_neg_pool) >= max_n:
                easy_pos_clip_indices = random.sample(rel_clip_ids, k=max_n)
                easy_neg_clip_indices = random.sample(easy_neg_pool, k=max_n)
            else:  # copy the hard ones
                easy_pos_clip_indices = hard_pos_clip_indices
                easy_neg_clip_indices = hard_neg_clip_indices

        pos_clip_indices = hard_pos_clip_indices + easy_pos_clip_indices
        neg_clip_indices = hard_neg_clip_indices + easy_neg_clip_indices

        return pos_clip_indices, neg_clip_indices, score_array

    def get_span_labels(self, windows, ctx_l):
        """
        windows: list([st, ed]) in seconds. E.g. [[26, 36]], corresponding st_ed clip_indices [[13, 17]] (inclusive)
            Note a maximum of `self.max_windows` windows are used.
        returns Tensor of shape (#windows, 2), each row is [center, width] normalized by video length
        """
        if len(windows) > self.max_windows:
            random.shuffle(windows)
            windows = windows[:self.max_windows]

        lengths = []
        for w in windows:
            lengths.append(w[1]-w[0])

        if self.span_loss_type == "l1":
            windows = torch.Tensor(windows) / (ctx_l * self.clip_len)  # normalized windows in xx
            windows = span_xx_to_cxw(windows)  # normalized windows in cxw
        elif self.span_loss_type == "ce":
            windows = torch.Tensor([
                [int(w[0] / self.clip_len), min(int(w[1] / self.clip_len), ctx_l) - 1]
                for w in windows]).long()  # inclusive
        else:
            raise NotImplementedError
        return windows, lengths

    def _get_query_feat_by_qid(self, qid):
        if self.dset_name == 'tvsum':
            q_feat = np.load(join(self.q_feat_dir, "{}.npz".format(qid))) # 'token', 'text'
            return torch.from_numpy(q_feat['token'])
        else:
            # QVhighlight dataset
            q_feat_path = join(self.q_feat_dir, f"qid{qid}.npz")
            q_feat = np.load(q_feat_path)[self.q_feat_type].astype(np.float32)
            if self.q_feat_type == "last_hidden_state":
                q_feat = q_feat[:self.max_q_l]
            if self.normalize_t:
                q_feat = l2_normalize_np_array(q_feat)
            if self.txt_drop_ratio > 0:
                q_feat = self.random_drop_rows(q_feat)
        return torch.from_numpy(q_feat)  # (D, ) or (Lq, D)

    def _get_clip_text_feat(self, query):
        if self.dset_name == 'tvsum':
            q_feat = np.load(join(self.q_feat_dir, "{}.npz".format(qid))) # 'token', 'text'
            return torch.from_numpy(q_feat['token'])
        else:
            # QVhighlight dataset
            encoded_query = clip.tokenize([query]).to(self.device)
            
            with torch.no_grad():
                q_feat = self.clip_model.encode_text_hidden_state(encoded_query)
                
                pad_start_idx = torch.nonzero(encoded_query[0]).flatten()[-1] + 1
                q_feat = q_feat[0][:pad_start_idx]

            if self.q_feat_type == "last_hidden_state":
                q_feat = q_feat[:self.max_q_l]
            if self.normalize_t:
                # q_feat = l2_normalize_np_array(q_feat)
                q_feat = q_feat / q_feat.norm(dim=-1, keepdim=True)
            if self.txt_drop_ratio > 0:
                q_feat = self.random_drop_rows(q_feat)

        return q_feat  # (D, ) or (Lq, D)

    def _get_global_local_features(self, query, r=0.5):
        # sentence -> final feature (global)
        # noun -> final feature (local)
        # final = global + local
        if self.dset_name == 'tvsum':
            q_feat = np.load(join(self.q_feat_dir, "{}.npz".format(qid))) # 'token', 'text'
            return torch.from_numpy(q_feat['token'])
        else:
            # QVhighlight dataset

            query_ = query.lower()
            doc = self.nlp(query_)

            sentence_for_spacy = []

            for i, token in enumerate(doc):
                if token.text == ' ':
                    continue
                sentence_for_spacy.append(token.text)

            sentence_for_spacy = ' '.join(sentence_for_spacy)
            sentence_token = clip.tokenize(sentence_for_spacy).to(self.device)
            noun_phrase, not_phrase_index, head_noun = self.extract_noun_phrase(sentence_for_spacy, need_index=True)
            noun_phrase_token = clip.tokenize(noun_phrase).to(self.device)

            with torch.no_grad():
                sentence_features =self.clip_model.encode_text(sentence_token)
                noun_phrase_features = self.clip_model.encode_text(noun_phrase_token)

            q_feat = r * sentence_features + (1-r) * noun_phrase_features

            if self.normalize_t:
                q_feat = q_feat / q_feat.norm(dim=-1, keepdim=True)
                
            if self.txt_drop_ratio > 0:
                q_feat = self.random_drop_rows(q_feat)

        return q_feat  # (D, ) or (Lq, D)

    def _get_hidden_features(self, query, r=0.5):
        # sentence -> last hidden state
        # sen + noun -> final feature
        # final = last hidden state + final feature
        if self.dset_name == 'tvsum':
            q_feat = np.load(join(self.q_feat_dir, "{}.npz".format(qid))) # 'token', 'text'
            return torch.from_numpy(q_feat['token'])
        else:
            # QVhighlight dataset
  
            query_ = query.lower()
            doc = self.nlp(query_)

            sentence_for_spacy = []

            for i, token in enumerate(doc):
                if token.text == ' ':
                    continue
                sentence_for_spacy.append(token.text)

            sentence_for_spacy = ' '.join(sentence_for_spacy)
            sentence_token = clip.tokenize(sentence_for_spacy).to(self.device)
            noun_phrase, phrase_index, not_phase_index = self.extract_noun_phrase(sentence_for_spacy, need_index=True)
            noun_phrase_token = clip.tokenize(noun_phrase).to(self.device)

            
            with torch.no_grad():
                # 1) sentence last hidden state
                sen_hidden_state = self.clip_model.encode_text_hidden_state(sentence_token)

                pad_start_idx = torch.nonzero(sentence_token[0]).flatten()[-1] + 1
                sen_hidden_state = sen_hidden_state[0][:pad_start_idx]

                if self.q_feat_type == "last_hidden_state":
                    sen_hidden_state = sen_hidden_state[:self.max_q_l]


                # 2) sen + noun final features
                sentence_features =self.clip_model.encode_text(sentence_token)
                noun_phrase_features = self.clip_model.encode_text(noun_phrase_token)

            # 2) sen + noun final features
            text_ensemble = r * sentence_features + (1-r) * noun_phrase_features

            # normalize
            if self.normalize_t:
                sen_hidden_state = sen_hidden_state / sen_hidden_state.norm(dim=-1, keepdim=True)     
                final_feat = text_ensemble / text_ensemble.norm(dim=1, keepdim=True)

            # 3) concat 1) and 2)
            q_feat = torch.concat((sen_hidden_state, final_feat), dim=0)

            if self.txt_drop_ratio > 0:
                q_feat = self.random_drop_rows(q_feat)

        return q_feat  # (D, ) or (Lq, D)
    
    def _get_global_local_hidden_states(self, query, r=0.5):
        # sentence -> last hidden state (global)
        # noun -> last hidden state (local)
        # final = local + global
        if self.dset_name == 'tvsum':
            q_feat = np.load(join(self.q_feat_dir, "{}.npz".format(qid))) # 'token', 'text'
            return torch.from_numpy(q_feat['token'])
        else:
            # QVhighlight dataset

            query_ = query.lower()
            doc = self.nlp(query_)

            sentence_for_spacy = []

            for i, token in enumerate(doc):
                if token.text == ' ':
                    continue
                sentence_for_spacy.append(token.text)

            sentence_for_spacy = ' '.join(sentence_for_spacy)
            sentence_token = clip.tokenize(sentence_for_spacy).to(self.device)
            noun_phrase, phrase_index, not_phrase_index = self.extract_noun_phrase(sentence_for_spacy, need_index=True)
            noun_phrase_token = clip.tokenize(noun_phrase).to(self.device)
            
            with torch.no_grad():
                # 1) sentence last hidden state
                sen_hidden_state = self.clip_model.encode_text_hidden_state(sentence_token)
        
                # 2) noun last hidden state
                noun_hidden_state = self.clip_model.encode_text_hidden_state(noun_phrase_token)
                
                only_noun_hidden_state = torch.zeros_like(sen_hidden_state)
                for idx in phrase_index:
                    only_noun_hidden_state[0][idx+1] = noun_hidden_state[0][idx+1]

                pad_start_idx = torch.nonzero(sentence_token[0]).flatten()[-1] + 1

                sen_hidden_state = sen_hidden_state[0][:pad_start_idx]
                only_noun_hidden_state = only_noun_hidden_state[0][:pad_start_idx]

                if self.q_feat_type == "last_hidden_state":
                    sen_hidden_state = sen_hidden_state[:self.max_q_l]
                    only_noun_hidden_state = only_noun_hidden_state[:self.max_q_l]

            q_feat = r * sen_hidden_state + (1-r) * only_noun_hidden_state

            if self.q_feat_type == "last_hidden_state":
                q_feat = q_feat[:self.max_q_l]

            if self.normalize_t:
                q_feat = q_feat / q_feat.norm(dim=-1, keepdim=True)

            if self.txt_drop_ratio > 0:
                q_feat = self.random_drop_rows(q_feat)

        return q_feat  # (D, ) or (Lq, D)

    def _get_only_noun_hidden_states(self, query):
        # sentence -> last hidden state (global)
        # noun -> last hidden state (local)
        # final = local + global
        if self.dset_name == 'tvsum':
            q_feat = np.load(join(self.q_feat_dir, "{}.npz".format(qid))) # 'token', 'text'
            return torch.from_numpy(q_feat['token'])
        else:
            # QVhighlight dataset

            query_ = query.lower()
            doc = self.nlp(query_)

            sentence_for_spacy = []

            for i, token in enumerate(doc):
                if token.text == ' ':
                    continue
                sentence_for_spacy.append(token.text)

            sentence_for_spacy = ' '.join(sentence_for_spacy)
            noun_phrase, phrase_index, not_phrase_index = self.extract_noun_phrase(sentence_for_spacy, need_index=True)
            noun_phrase_token = clip.tokenize(noun_phrase).to(self.device)
            
            with torch.no_grad():

                # noun last hidden state
                noun_hidden_state = self.clip_model.encode_text_hidden_state(noun_phrase_token)

                pad_start_idx = torch.nonzero(noun_phrase_token[0]).flatten()[-1] + 1

                q_feat = noun_hidden_state[0][:pad_start_idx]

            if self.q_feat_type == "last_hidden_state":
                q_feat = q_feat[:self.max_q_l]

            if self.normalize_t:
                q_feat = q_feat / q_feat.norm(dim=-1, keepdim=True)

            if self.txt_drop_ratio > 0:
                q_feat = self.random_drop_rows(q_feat)

        return q_feat  # (D, ) or (Lq, D)
    
    def extract_noun_phrase(self, text, need_index=False):
        
        text = text.lower()

        doc = self.nlp(text)

        chunks = {}
        chunks_index = {}
        for chunk in doc.noun_chunks:
            for i in range(chunk.start, chunk.end):
                chunks[i] = chunk
                chunks_index[i] = (chunk.start, chunk.end)

        for token in doc:
            if token.head.i == token.i:
                head = token.head

        if head.i not in chunks:
            children = list(head.children)
            if children and children[0].i in chunks:
                head = children[0]
            else:
                if need_index:
                    return text, [], text
                else:
                    return text

        head_index = chunks_index[head.i]
        head_index = [i for i in range(head_index[0], head_index[1])]

        sentence_index = [i for i in range(len(doc))]
        phrase_index = []
        not_phrase_index = []
        for i in sentence_index:
            if i in head_index:
                phrase_index.append(i)
            else:
                not_phrase_index.append(i)

        head = chunks[head.i]
        if need_index:
            return head.text, phrase_index, not_phrase_index
        else:
            return head.text

    def random_drop_rows(self, embeddings):
        """randomly mask num_drop rows in embeddings to be zero.
        Args:
            embeddings: np.ndarray (L, D)
        """
        num_drop_rows = round(len(embeddings) * self.txt_drop_ratio)
        if num_drop_rows > 0:
            row_indices = np.random.choice(
                len(embeddings), size=num_drop_rows, replace=False)
            embeddings[row_indices] = 0
        return embeddings

    def _get_video_feat_by_vid(self, vid):
        if self.dset_name == 'tvsum':
            v_feat_list = []
            for _feat_dir in self.v_feat_dirs:
                _feat_path = join(_feat_dir, f"{vid}_rgb.npy")
                _feat_rgb = np.load(_feat_path)[:self.max_v_l].astype(np.float32)

                _feat_path = join(_feat_dir, f"{vid}_opt.npy")
                _feat_opt = np.load(_feat_path)[:self.max_v_l].astype(np.float32)
                
                _feat = np.concatenate([_feat_rgb, _feat_opt], axis=-1)
                # _feat = _feat_rgb
                if self.normalize_v:
                    _feat = l2_normalize_np_array(_feat)
                v_feat_list.append(_feat)
            # some features are slightly longer than the others
            min_len = min([len(e) for e in v_feat_list])
            v_feat_list = [e[:min_len] for e in v_feat_list]
            v_feat = np.concatenate(v_feat_list, axis=1)

        else:
            v_feat_list = []
            for _feat_dir in self.v_feat_dirs:
                _feat_path = join(_feat_dir, f"{vid}.npz")
                _feat = np.load(_feat_path)["features"][:self.max_v_l].astype(np.float32)
                if self.normalize_v:
                    _feat = l2_normalize_np_array(_feat)
                v_feat_list.append(_feat)
            # some features are slightly longer than the others
            min_len = min([len(e) for e in v_feat_list])
            v_feat_list = [e[:min_len] for e in v_feat_list]
            v_feat = np.concatenate(v_feat_list, axis=1)
        return torch.from_numpy(v_feat)  # (Lv, D)



def start_end_collate(batch):
    batch_meta = [e["meta"] for e in batch]  # seems no need to collate ?

    model_inputs_keys = batch[0]["model_inputs"].keys()
    batched_data = dict()
    for k in model_inputs_keys:
        if k == "span_labels":
            batched_data[k] = [dict(spans=e["model_inputs"]["span_labels"]) for e in batch]
            continue
        if k in ["saliency_pos_labels", "saliency_neg_labels"]:
            batched_data[k] = torch.LongTensor([e["model_inputs"][k] for e in batch])
            continue
        if k == "saliency_all_labels":
            pad_data, mask_data = pad_sequences_1d([e["model_inputs"][k] for e in batch], dtype=np.float32, fixed_length=None)
            # print(pad_data, mask_data)
            batched_data[k] = torch.tensor(pad_data, dtype=torch.float32)
            continue
        if k == "moment_class":
            batched_data[k] = [dict(m_cls=e["model_inputs"]["moment_class"]) for e in batch]
            continue

        batched_data[k] = pad_sequences_1d(
            [e["model_inputs"][k] for e in batch], dtype=torch.float32, fixed_length=None)
    return batch_meta, batched_data


def prepare_batch_inputs(batched_model_inputs, device, non_blocking=False):
    model_inputs = dict(
        src_txt=batched_model_inputs["query_feat"][0].to(device, non_blocking=non_blocking),
        src_txt_mask=batched_model_inputs["query_feat"][1].to(device, non_blocking=non_blocking),
        src_vid=batched_model_inputs["video_feat"][0].to(device, non_blocking=non_blocking),
        src_vid_mask=batched_model_inputs["video_feat"][1].to(device, non_blocking=non_blocking),
    )
    targets = {}
    if "span_labels" in batched_model_inputs:
        targets["span_labels"] = [
            dict(spans=e["spans"].to(device, non_blocking=non_blocking))
            for e in batched_model_inputs["span_labels"]
        ]
    if "saliency_pos_labels" in batched_model_inputs:
        for name in ["saliency_pos_labels", "saliency_neg_labels"]:
            targets[name] = batched_model_inputs[name].to(device, non_blocking=non_blocking)

    if "saliency_all_labels" in batched_model_inputs:
        targets["saliency_all_labels"] = batched_model_inputs["saliency_all_labels"].to(device, non_blocking=non_blocking)
    
    if "moment_class" in batched_model_inputs:
        targets["moment_class"] = [
            dict(m_cls=e["m_cls"].to(device, non_blocking=non_blocking))
            for e in batched_model_inputs["moment_class"]
        ]
    
    targets = None if len(targets) == 0 else targets
    return model_inputs, targets
