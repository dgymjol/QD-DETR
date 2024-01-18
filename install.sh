conda create -n moment python==3.9
conda activate moment

pip install torch==1.11.0+cu113 torchvision==0.12.0+cu113 torchaudio==0.11.0 --extra-index-url https://download.pytorch.org/whl/cu113
conda install git wget tmux gpustat -y

git clone https://github.com/dgymjol/moment_detr.git
cd moment-detr

pip install tqdm ipython easydict tensorboard tabulate scikit-learn pandas


# training
bash moment_detr/scripts/train.sh 
