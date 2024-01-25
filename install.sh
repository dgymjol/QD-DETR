conda update --all
conda update -n base conda

conda create -n mr python==3.9
conda activate mr

pip install torch==1.12.0+cu113 torchvision==0.13.0+cu113 torchaudio==0.12.0 --extra-index-url https://download.pytorch.org/whl/cu113
conda install git wget tmux gpustat -y

git clone https://github.com/dgymjol/moment_detr.git
cd moment-detr

pip install tqdm ipython easydict tensorboard tabulate scikit-learn pandas ipykernel ftfy

# training
bash moment_detr/scripts/train.sh 



#clip
pip install ftfy regex tqdm
pip install git+https://github.com/openai/CLIP.git

# spacy
conda install -c conda-forge spacy
# 위에 안되면..
pip install -U pip setuptools wheel
pip install -U 'spacy[cuda113]'



pip install pydantic==1.10.11 --upgrade

python -m spacy download en_core_web_lg


# 위에 명령어 실행 시 에러나면 아래꺼 차례로 실행 후 다시 해보기
sudo apt-get update
sudo apt-get install software-properties-common
sudo add-apt-repository ppa:ubuntu-toolchain-r/test
sudo apt-get install gcc-5
sudo apt-get upgrade libstdc++6
