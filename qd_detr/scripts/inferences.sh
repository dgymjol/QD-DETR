eval_split_name=$1
eval_path=data/highlight_${eval_split_name}_release.jsonl
echo ${eval_split_name}
echo ${eval_path}



list="results/hl-video_tef-exp-2024_01_22_08_48_56/model_best.ckpt results/hl-video_tef-exp-2024_01_22_08_49_31/model_best.ckpt results/hl-video_tef-exp-2024_01_22_14_51_12/model_best.ckpt results/hl-video_tef-exp-2024_01_22_08_50_15/model_best.ckpt results/hl-video_tef-exp-2024_01_22_08_49_56/model_best.ckpt results/hl-video_tef-exp-2024_01_22_14_51_15/model_best.ckpt results/hl-video_tef-exp-2024_01_22_14_49_25/model_best.ckpt"
 
for var in $list
do
  echo $var

  PYTHONPATH=$PYTHONPATH:. python qd_detr/inference.py \
  --resume ${var} \
  --eval_split_name ${eval_split_name} \
  --eval_path ${eval_path} \
${@:3}
done
