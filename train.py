import pickle
import os
import pandas as pd
import torch
from torch.utils.data import RandomSampler, DataLoader
import sklearn
import numpy as np
from sklearn.metrics import accuracy_score, recall_score, precision_score, f1_score
from transformers import AutoTokenizer, AutoConfig, AutoModelForSequenceClassification, Trainer, TrainingArguments, RobertaConfig, RobertaTokenizer, RobertaForSequenceClassification, BertTokenizer, set_seed
from load_data import *
from model import R_BigBird
import wandb

wandb.init(project='klue', entity='klue')

def klue_re_micro_f1(preds, labels):
    """KLUE-RE micro f1 (except no_relation)"""
    label_list = ['no_relation', 'org:top_members/employees', 'org:members',
       'org:product', 'per:title', 'org:alternate_names',
       'per:employee_of', 'org:place_of_headquarters', 'per:product',
       'org:number_of_employees/members', 'per:children',
       'per:place_of_residence', 'per:alternate_names',
       'per:other_family', 'per:colleagues', 'per:origin', 'per:siblings',
       'per:spouse', 'org:founded', 'org:political/religious_affiliation',
       'org:member_of', 'per:parents', 'org:dissolved',
       'per:schools_attended', 'per:date_of_death', 'per:date_of_birth',
       'per:place_of_birth', 'per:place_of_death', 'org:founded_by',
       'per:religion']
    no_relation_label_idx = label_list.index("no_relation")
    label_indices = list(range(len(label_list)))
    label_indices.remove(no_relation_label_idx)
    return sklearn.metrics.f1_score(labels, preds, average="micro", labels=label_indices) * 100.0

def klue_re_auprc(probs, labels):
    """KLUE-RE AUPRC (with no_relation)"""
    labels = np.eye(30)[labels]

    score = np.zeros((30,))
    for c in range(30):
        targets_c = labels.take([c], axis=1).ravel()
        preds_c = probs.take([c], axis=1).ravel()
        precision, recall, _ = sklearn.metrics.precision_recall_curve(targets_c, preds_c)
        score[c] = sklearn.metrics.auc(recall, precision)
    return np.average(score) * 100.0

def compute_metrics(pred):
    """ validation을 위한 metrics function """
    labels = pred.label_ids
    preds = pred.predictions.argmax(-1)
    probs = pred.predictions

    # calculate accuracy using sklearn's function
    f1 = klue_re_micro_f1(preds, labels)
    auprc = klue_re_auprc(probs, labels)
    acc = accuracy_score(labels, preds) # 리더보드 평가에는 포함되지 않습니다.

    return {
        'micro f1 score': f1,
        'auprc' : auprc,
        'accuracy': acc,
    }

def label_to_num(label):
    num_label = []
    with open('dict_label_to_num.pkl', 'rb') as f:
        dict_label_to_num = pickle.load(f)
    for v in label:
        num_label.append(dict_label_to_num[v])
    
    return num_label

def train():
    set_seed(42)
    # load model and tokenizer
    tokenizer = AutoTokenizer.from_pretrained('klue/roberta-large')
    
    # load dataset
    dataset = load_data_for_R('../dataset/train/train_sub.csv')

    num_splits = 5
    for fold, (train_dataset,dev_dataset) in enumerate(split_data(dataset, num_splits=num_splits), 1):
        # tokenizing dataset
        tokenized_train, train_label = convert_sentence_to_features(train_dataset, tokenizer, 256)
        tokenized_dev, dev_label = convert_sentence_to_features(dev_dataset, tokenizer, 256)


        train_label = label_to_num(train_label)
        dev_label = label_to_num(dev_label)

        # make dataset for pytorch.
        RE_train_dataset = RE_Dataset_for_R(tokenized_train, train_label, train=True)
        RE_dev_dataset = RE_Dataset_for_R(tokenized_dev, dev_label, train=True)

        device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

        # setting model hyperparameter
        model_config =  AutoConfig.from_pretrained('klue/roberta-large')
        # model_config.num_labels = 30

        model = R_BigBird(model_config, 0.1)
        model.model.resize_token_embeddings(tokenizer.vocab_size + 12)
        # model.parameters
        model.to(device)
    
    # 사용한 option 외에도 다양한 option들이 있습니다.
    # https://huggingface.co/transformers/main_classes/trainer.html#trainingarguments 참고해주세요.
        training_args = TrainingArguments(
        output_dir='./results',          # output directory
        save_total_limit=5,              # number of total save model.
        save_steps=500,                 # model saving step.
        num_train_epochs=4,              # total number of training epochs
        learning_rate=5e-5,               # learning_rate
        per_device_train_batch_size=32,  # batch size per device during training
        per_device_eval_batch_size=32,   # batch size for evaluation
        warmup_steps=500,                # number of warmup steps for learning rate scheduler
        weight_decay=0.01,               # strength of weight decay
        logging_dir='./logs',            # directory for storing logs
        logging_steps=500,              # log saving step.
        evaluation_strategy='epoch',
        save_strategy='epoch', # evaluation strategy to adopt during training
                                    # `no`: No evaluation during training.
                                    # `steps`: Evaluate every `eval_steps`.
                                    # `epoch`: Evaluate every end of epoch.
        eval_steps = 100,            # evaluation step.
        load_best_model_at_end = True, 
        report_to='wandb'
        )
        trainer = Trainer(
        model=model,                         # the instantiated 🤗 Transformers model to be trained
        args=training_args,                  # training arguments, defined above
        train_dataset=RE_train_dataset,         # training dataset
        eval_dataset=RE_dev_dataset,             # evaluation dataset
        compute_metrics=compute_metrics         # define metrics function
        )

        # train model
        trainer.train()
        if num_splits == 1:
            best_dir = f'./best_model'
        else: best_dir = f'./best_model/{fold}_best_model'

        os.makedirs(best_dir, exist_ok=True)
        model.save_pretrained(best_dir)
        #model.save_pretrained('./best_model')

def main():
    train()

if __name__ == '__main__':
    main()
