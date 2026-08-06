# script for joining human review prelimiary review data
# output data from excel into hf datasets

import pandas as pd
from pathlib import Path
import os
from datasets import Dataset 

base_path = Path(".")
files = base_path.glob("raw_pr/*.xlsx")
full = pd.concat([pd.read_excel(f) for f in files])
full = full[["Article ID", "body_text", "Meets inclusion criteria (Y/N)"]]
full = full.rename(columns={"Meets inclusion criteria (Y/N)": "label", "Article ID":"id", "body_text":"text"})
full = full.dropna(subset=["label", "text"])
full['label'] = full['label'].apply(lambda x: x[0].upper())
full = full.drop(full[full.label == "C"].index).reset_index(drop=True)

dset = Dataset.from_pandas(full)
dset.save_to_disk("human-pr")
