# for training and validating the classifier from step 0
# see /docs for more imformation

from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer, DataCollatorWithPadding, EarlyStoppingCallback
import torch
import torch.nn.functional as F
import numpy as np
from datasets import Dataset, DatasetDict, Value
import pandas as pd
import evaluate
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay, classification_report
import matplotlib.pyplot as plt

# globals
SEED = 2718
TEST_RATIO = 0.1
VAL_RATIO = 0.2
MAX_LENGTH = 2048
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MODEL_PATH = "/cluster/tufts/tuftsai/models/answerdotai_ModernBERT-large"
ID2LABEL = {0:"N", 1:"Y"}
LABEL2ID = {"N":0, "Y":1}
THRESHOLD = 0.5
POS_ID = LABEL2ID["Y"]

# model and tokenizer
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH, num_labels=2, id2label=ID2LABEL, label2id=LABEL2ID).to(DEVICE)

# dataset
## we have about 10x negative examples to positive examples
## here we use the seed to choose a random sample of negative examples to match the number of positive examples
## using pandas because it's easier for me that HF datasets
human_pr = Dataset.load_from_disk("human-pr").to_pandas()
num_pos = len(human_pr[human_pr.label == "Y"])
sam_neg = human_pr[human_pr.label == "N"].sample(n=num_pos, random_state=SEED)
dset = Dataset.from_pandas(pd.concat([human_pr[human_pr.label == "Y"], sam_neg]).reset_index(drop=True).sample(frac=1, random_state=SEED, ignore_index=True))
dset = dset.class_encode_column("label")

## splits
train_val_test = dset.train_test_split(test_size=TEST_RATIO, stratify_by_column="label", seed=SEED)
test_dset = train_val_test["test"]
train_val_dset = train_val_test["train"]
val_frac_of_remainder = VAL_RATIO / (1 - TEST_RATIO)
train_val_split = train_val_dset.train_test_split(test_size=val_frac_of_remainder, stratify_by_column="label", seed=SEED)

train_dset = train_val_split["train"]
val_dset = train_val_split["test"]
split_dset = DatasetDict({"train":train_dset, "validation":val_dset})
test_dset.save_to_disk("held-out-test")

# data prep
## tokenization -> dataloading
def preprocess_function(examples):
    encoded = tokenizer(examples["text"], truncation=True, max_length=MAX_LENGTH, padding=False)
    # encoded["label"] = [LABEL2ID[l] for l in examples["label"]]
    return encoded
tokenized = split_dset.map(preprocess_function, batched=True, remove_columns=["id", "text"], load_from_cache_file=False)
tokenized = tokenized.cast_column("label", Value("int64"))
tokenized.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])
data_collator = DataCollatorWithPadding(tokenizer=tokenizer)
f1 = evaluate.load("f1")
def compute_metrics(eval_pred):
    preds, labels = eval_pred
    preds = np.argmax(preds, axis=1)
    return f1.compute(predictions=preds, references=labels)

# training
training_args = TrainingArguments(
    output_dir="pr-classifier",
    learning_rate=2e-5,
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    gradient_accumulation_steps=8,
    num_train_epochs=10,
    weight_decay=0.01,
    eval_strategy="epoch",
    save_strategy="epoch",
    save_total_limit=2,
    load_best_model_at_end=True,
    metric_for_best_model="f1",
    gradient_checkpointing=True,
    gradient_checkpointing_kwargs={"use_reentrant":False},
    bf16=True,
    optim="adamw_bnb_8bit",
    greater_is_better=True
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized['train'],
    eval_dataset=tokenized['validation'],
    processing_class=tokenizer,
    data_collator=data_collator,
    compute_metrics=compute_metrics,
    callbacks=[EarlyStoppingCallback(early_stopping_patience=3)]
)

trainer.train()

# inference
trained_model = trainer.model
tokenized_test = test_dset.map(preprocess_function, batched=True, remove_columns=["id", "text"])
tokenized_test.set_format(type="torch", columns=["input_ids", "attention_mask", "label"])
texts = test_dset["text"]
ids = test_dset["id"]

test_trainer = Trainer(
    model=trained_model,
    args=TrainingArguments(
        output_dir="tmp_inference",
        per_device_eval_batch_size=2,
        report_to="none"
    ),
    data_collator=data_collator
)

predictions = test_trainer.predict(tokenized_test)
labels = predictions.label_ids

probs = F.softmax(torch.tensor(predictions.predictions), dim=-1).numpy()
pos_probs = probs[:, POS_ID]
preds = (pos_probs >= THRESHOLD).astype(int)

label_names = [ID2LABEL[i] for i in range(len(ID2LABEL))]
print(f"--- threshold = {THRESHOLD} ---")
print(classification_report(labels, preds, target_names=label_names))

cm = confusion_matrix(labels, preds)
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=label_names)
disp.plot(cmap="Blues", values_format="d")
plt.title("Confusion Matrix")
plt.tight_layout()
plt.savefig("confusion-matrix.png", dpi=200)

# false positive/negative analysis
fp_mask = (preds == 1) & (labels == 0)
fn_mask = (preds == 0) & (labels == 1)
tp_mask = (preds == 1) & (labels == 1)
tn_mask = (preds == 0) & (labels == 0)

n_fp, n_fn, n_tp, n_tn = fp_mask.sum(), fn_mask.sum(), tp_mask.sum(), tn_mask.sum()
fnr = n_fn / (n_fn + n_tp) if (n_fn + n_tp) > 0 else float("nan")
fpr = n_fp / (n_fp + n_tn) if (n_fp + n_tn) > 0 else float("nan")

print("\n--- error breakdown ---")
print(f"True positives: {n_tp}")
print(f"True negatives: {n_tn}")
print(f"False positives: {n_fp} (False Positive Recall = {fpr:.3f})")
print(f"False negatives: {n_fn} (False Negative Recall = {fnr:.3f})")

error_df = pd.DataFrame({
    "id": ids,
    "text": texts,
    "true_label": [ID2LABEL[l] for l in labels],
    "pred_label": [ID2LABEL[p] for p in preds],
    "p_positive": pos_probs,
    "error_type": np.select([fp_mask, fn_mask], ["false_positive", "false_negative"], default="correct")
})
error_df[error_df.error_type != "correct"].sort_values("error_type").to_csv("error_analysis.csv", index=False)

# threshold sweeps
print("\n--- threshold sweep (positive class) ---")
print(f"{'threshold':>9} | {'precision':>9} | {'recall':>9} | {'FN count':>8} | {'FP count':>8}")
for t in np.arange(0.1, 1.0, 0.1):
    sweep_preds = (pos_probs >= t).astype(int)
    sweep_fn = ((sweep_preds == 0) & (labels == 1)).sum()
    sweep_tp = ((sweep_preds == 1) & (labels == 1)).sum()
    sweep_fp = ((sweep_preds == 1) & (labels == 0)).sum()
    precision = sweep_tp / (sweep_tp + sweep_fp) if (sweep_tp + sweep_fp) > 0 else float("nan")
    recall = sweep_tp / (sweep_tp + sweep_fn) if (sweep_tp + sweep_fn) > 0 else float("nan")
    print(f"{t:>9.1f} | {precision:>9.3f} | {recall:>9.3f} | {sweep_fn:>8d} | {sweep_fp:>8}")
