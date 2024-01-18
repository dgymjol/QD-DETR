# qvhighlights
wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id=1Hiln02F1NEpoW8-iPZurRyi-47-W2_B9' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id=1Hiln02F1NEpoW8-iPZurRyi-47-W2_B9" -O moment_detr_features.tar.gz && rm -rf /tmp/cookies.txt
tar -xf moment_detr_features.tar.gz

# charades
wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id=1B2721QC799qbbGLGSa7DkXJjdRefvZf-' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id=1B2721QC799qbbGLGSa7DkXJjdRefvZf-" -O charades.zip && rm -rf /tmp/cookies.txt
unzip charades.zip

# tacos
wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id=1_IaKMjKw3nNaSsvN28ZucfM4K-ivZTHw' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id=1_IaKMjKw3nNaSsvN28ZucfM4K-ivZTHw" -O tacos.zip && rm -rf /tmp/cookies.txt
unzip tacos.zip

# tvsum
wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id=10Ji9MrlDK_4FdD3HotrVc407xVr4arsL' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id=10Ji9MrlDK_4FdD3HotrVc407xVr4arsL" -O tvsum.zip && rm -rf /tmp/cookies.txt
unzip tvsum.zip

# youtube
wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id=1qVhb33ABnWqiHjT22f54fKhSlf2Z-z0f' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id=1qVhb33ABnWqiHjT22f54fKhSlf2Z-z0f" -O youtube_uni.zip && rm -rf /tmp/cookies.txt
unzip youtube_uni.zip
