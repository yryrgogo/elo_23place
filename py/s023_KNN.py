out_part = ['', 'part', 'all'][0]
outlier_thres = -3
num_threads = 36
import sys
import pandas as pd

from sklearn import neighbors
knn = 300
knn = neighbors.KNeighborsRegressor(n_jobs=num_threads, n_neighbors=300)


#========================================================================
# Args
#========================================================================
key = 'card_id'
target = 'target'
ignore_list = [key, target, 'merchant_id', 'first_active_month', 'index', 'personal_term']

stack_name='en_route'
fname=''
xray=False
#  xray=True
submit = pd.read_csv('../input/sample_submission.csv')
#  submit = []


model_type='lgb'
try:
    learning_rate = float(sys.argv[1])
except ValueError:
    learning_rate = 0.01
early_stopping_rounds = 200
#  early_stopping_rounds = 150
num_boost_round = 5000

import numpy as np
import datetime
import glob
import gc
import os
from sklearn.metrics import mean_squared_error
HOME = os.path.expanduser('~')

sys.path.append(f'{HOME}/kaggle/data_analysis/model')
from params_lgbm import params_elo
sys.path.append(f'{HOME}/kaggle/data_analysis')
from model.lightgbm_ex import lightgbm_ex as lgb_ex

sys.path.append(f"{HOME}/kaggle/data_analysis/library/")
import utils
from preprocessing import get_ordinal_mapping
from utils import logger_func
try:
    if not logger:
        logger=logger_func()
except NameError:
    logger=logger_func()


start_time = "{0:%Y%m%d_%H%M%S}".format(datetime.datetime.now())

#========================================================================
# Data Load

win_path = f'../features/4_winner/*.gz'
tmp_path_list = glob.glob(f'../features/5_tmp/*.gz') + glob.glob(f'../features/0_exp/*.gz')

base = utils.read_df_pkl('../input/base_first*')
base_train = base[~base[target].isnull()].reset_index(drop=True)
base_test = base[base[target].isnull()].reset_index(drop=True)

win_path_list = glob.glob(win_path) + tmp_path_list
feature_list = utils.parallel_load_data(path_list=win_path_list)

# サイズチェック
#  for f in feature_list:
#      if f.shape[0]>330000:
#          print(f.name)
#  sys.exit()

df_feat = pd.concat(feature_list, axis=1)

#  df_feat['pred_new'] = utils.read_pkl_gzip('../stack/0205_220_stack_pred_556_lif_hist_regist_term_lift_203_pst_ratio_new_auth1_purchase_amount_sum_lr0.01_145feats_1seed_68leaves_iter2261_CV1-6957022874138066.gz').iloc[:, 1]
#  df_feat.loc[len(base_train):, 'pred_new'] = 0
#  df_feat['pred_new'] -= df_feat['556_lif_hist_regist_term_lift_203_pst_ratio_new_auth1_purchase_amount_sum@']
#  df_feat.drop(['556_lif_hist_regist_term_lift_203_pst_ratio_new_auth1_purchase_amount_sum@'], axis=1, inplace=True)

train = pd.concat([base_train, df_feat.iloc[:len(base_train), :]], axis=1)
test = pd.concat([base_test, df_feat.iloc[len(base_train):, :].reset_index(drop=True)], axis=1)

#========================================================================
# card_id list by first active month
if int(sys.argv[2])!=0:
    train_latest_id_list = np.load(f'../input/card_id_train_first_active_2017{sys.argv[2]}.npy')
    test_latest_id_list = np.load(f'../input/card_id_test_first_active_2017{sys.argv[2]}.npy')
    train = train.loc[train[key].isin(train_latest_id_list), :].reset_index(drop=True)
    test = test.loc[test[key].isin(test_latest_id_list), :].reset_index(drop=True)
    submit = []
else:
    pass
#========================================================================
y = train[target].values



#========================================================================

#========================================================================
# LGBM Setting
try:
    argv3 = int(sys.argv[3])
    seed_list = np.arange(argv3)
    if argv3<=10:
        seed_list = [1208, 605, 1212, 1222, 405, 1128, 1012, 328, 2005, 2019][:argv3]
        #  seed_list = [328, 605, 1212, 1222, 405, 1128, 1012, 1208, 2005, 2019][:argv3]
except IndexError:
    seed_list = [1208]
    #  seed_list = [328]
metric = 'rmse'
#  metric = 'mse'
params['metric'] = metric
fold=5
fold_type='self'
#  fold_type='stratified'
group_col_name=''
dummie=1
oof_flg=True
LGBM = lgb_ex(logger=logger, metric=metric, model_type=model_type, ignore_list=ignore_list)

#  train, test, drop_list = LGBM.data_check(train=train, test=test, target=target)
train, test, drop_list = LGBM.data_check(train=train, test=test, target=target, encode='label')
if len(drop_list):
    train.drop(drop_list, axis=1, inplace=True)
    test.drop(drop_list, axis=1, inplace=True)

from sklearn.model_selection import StratifiedKFold, KFold


# seed_avg
seed_pred = np.zeros(len(test))
cv_list = []
iter_list = []
model_list = []
train.reset_index(inplace=True, drop=True)
test.reset_index(inplace=True , drop=True)
for i, seed in enumerate(seed_list):

    if key not in train.columns:
        train.reset_index(inplace=True)
    if key not in test.columns:
        test.reset_index(inplace=True)

    LGBM = lgb_ex(logger=logger, metric=metric, model_type=model_type, ignore_list=ignore_list)
    LGBM.seed = seed

    #  if i>=5:
    #      params['num_leaves'] = 48
    #      params['subsample'] = 0.8757099996397999
    #      params['colsample_bytree'] = 0.7401342964627846
    #      params['min_child_samples'] = 61

    #========================================================================
    # Validation Setting vvv
    if sys.argv[4]=='ods':

        #========================================================================
        # ods.ai 3rd kernel
        # https://www.kaggle.com/c/elo-merchant-category-recommendation/discussion/78903
        # KFold: n_splits=6(or 7)!, shuffle=False!
        #========================================================================
        train['rounded_target'] = train['target'].round(0)
        train = train.sort_values('rounded_target').reset_index(drop=True)
        vc = train['rounded_target'].value_counts()
        vc = dict(sorted(vc.items()))
        df = pd.DataFrame()
        train['indexcol'],idx = 0,1
        for k,v in vc.items():
            step = train.shape[0]/v
            indent = train.shape[0]/(v+1)
            df2 = train[train['rounded_target'] == k].sample(v, random_state=seed).reset_index(drop=True)
            for j in range(0, v):
                df2.at[j, 'indexcol'] = indent + j*step + 0.000001*idx
            df = pd.concat([df2,df])
            idx+=1
        train = df.sort_values('indexcol', ascending=True).reset_index(drop=True)
        del train['indexcol'], train['rounded_target']
        fold_type = 'self'
        fold = 6
        folds = KFold(n_splits=fold, shuffle=False, random_state=seed)
        kfold = folds.split(train, train[target].values)


    # 3. Default KFold
    else:
        kfold = False
        fold_type = 'kfold'
    #========================================================================

    train.sort_index(axis=1, inplace=True)
    test.sort_index(axis=1, inplace=True)

    #========================================================================
    # Train & Prediction Start
    #========================================================================
    LGBM = LGBM.cross_prediction(
        train=train
        ,test=test
        ,key=key
        ,target=target
        ,fold_type=fold_type
        ,fold=fold
        ,group_col_name=group_col_name
        ,params=params
        ,num_boost_round=num_boost_round
        ,early_stopping_rounds=early_stopping_rounds
        ,oof_flg=oof_flg
        ,self_kfold=kfold
        #  ,comp_name='elo'
    )

    seed_pred += LGBM.prediction

    if i==0:
        cv_list.append(LGBM.cv_score)
        iter_list.append(LGBM.iter_avg)
        cv_feim = LGBM.cv_feim
        feature_num = len(LGBM.use_cols)
        df_pred = LGBM.result_stack.copy()
    else:
        cv_score = LGBM.cv_score
        cv_list.append(cv_score)
        iter_list.append(LGBM.iter_avg)
        LGBM.cv_feim.columns = [col if col.count('feature') else f"{col}_{seed}" for col in LGBM.cv_feim.columns]
        cv_feim = cv_feim.merge(LGBM.cv_feim, how='inner', on='feature')
        df_pred = df_pred.merge(LGBM.result_stack[[key, 'prediction']].rename(columns={'prediction':f'prediction_{i}'}), how='inner', on=key)


#========================================================================
# STACKING
if len(stack_name)>0:
    logger.info(f'result_stack shape: {df_pred.shape}')
    if len(seed_list)>1:
        pred_cols = [col for col in df_pred.columns if col.count('predict')]
        df_pred['pred_mean'] = df_pred[pred_cols].mean(axis=1)
        df_pred['pred_std'] = df_pred[pred_cols].std(axis=1)
#========================================================================


#========================================================================
# Result
cv_score = np.mean(cv_list)
iter_avg = np.int(np.mean(iter_list))
#========================================================================

logger.info(f'''
#========================================================================
# {len(seed_list)}SEED CV SCORE AVG: {cv_score}
#========================================================================''')

#========================================================================
# Part of card_id Score
bench = pd.read_csv('../input/bench_LB3684_FAM_cv_score.csv')
part_score_list = []
part_N_list = []
fam_list = []
#  for i in range(201101, 201713, 1):
for i in range(201501, 201713, 1):
    fam = str(i)[:4] + '-' + str(i)[-2:]
    df_part = base_train[base_train['first_active_month']==fam]
    if len(df_part)<1:
        continue
    part_id_list = df_part[key].values

    part_train = df_pred.loc[df_pred[key].isin(part_id_list), :]
    y_train = part_train[target].values
    if 'pred_mean' in list(part_train.columns):
        y_pred = part_train['pred_mean'].values
    else:
        y_pred = part_train['prediction'].values

    y_pred = np.where(y_pred != y_pred, 0, y_pred)
    # RMSE
    part_score = np.sqrt(mean_squared_error(y_train, y_pred))
    bench_score = bench[bench['FAM']==fam]['CV'].values[0]
    part_score -= bench_score

    fam_list.append(fam)
    part_score_list.append(part_score)
    part_N_list.append(len(part_id_list))

#  for i, part_score, N in zip(fam_list, part_score_list, part_N_list):
df = pd.DataFrame(np.asarray([fam_list, part_score_list, part_N_list]).T)
df.columns = ['FAM', 'CV', 'N']

# FAM: {i} | CV: {part_score} | N: {len(part_id_list)}
pd.set_option('max_rows', 200)
logger.info(f'''
#========================================================================
# {df}
#========================================================================''')
#========================================================================


if len(train)>150000:
    if len(train[train[target]<-30])>0:
        # outlierに対するスコアを出す
        train.reset_index(inplace=True)
        out_ids = train.loc[train.target<-30, key].values
        out_val = train.loc[train.target<-30, target].values
        if len(seed_list)==1:
            out_pred = df_pred[df_pred[key].isin(out_ids)]['prediction'].values
        else:
            out_pred = df_pred[df_pred[key].isin(out_ids)]['pred_mean'].values
        out_score = np.sqrt(mean_squared_error(out_val, out_pred))
    else:
        out_score = 0
else:
    out_score = 0

# Save
try:
    if int(sys.argv[2])==0:
        utils.to_pkl_gzip(path=f"../stack/{start_time[4:12]}_stack_{model_type}_lr{learning_rate}_{feature_num}feats_{len(seed_list)}seed_{num_leaves}leaves_iter{iter_avg}_OUT{str(out_score)[:7]}_CV{str(cv_score).replace('.', '-')}_LB", obj=df_pred)
except ValueError:
    pass
except TypeError:
    pass

# 不要なカラムを削除
drop_feim_cols = [col for col in cv_feim.columns if col.count('importance_') or col.count('rank_')]
cv_feim.drop(drop_feim_cols, axis=1, inplace=True)
drop_feim_cols = [col for col in cv_feim.columns if col.count('importance') and not(col.count('avg'))]
cv_feim.drop(drop_feim_cols, axis=1, inplace=True)
cv_feim.to_csv( f'../valid/{start_time[4:12]}_valid_{model_type}_lr{learning_rate}_{feature_num}feats_{len(seed_list)}seed_{num_leaves}leaves_iter{iter_avg}_OUT{str(out_score)[:7]}_CV{cv_score}_LB.csv' , index=False)

#========================================================================
# Submission
try:
    if int(sys.argv[2])==0:
        test_pred = seed_pred / len(seed_list)
        submit[target] = test_pred
        submit_path = f'../submit/{start_time[4:12]}_submit_{model_type}_lr{learning_rate}_{feature_num}feats_{len(seed_list)}seed_{num_leaves}leaves_iter{iter_avg}_OUT{str(out_score)[:7]}_CV{cv_score}_LB.csv'
        submit.to_csv(submit_path, index=False)
except ValueError:
    pass
except TypeError:
    pass
#========================================================================

#========================================================================
# CV INFO

try:
    if int(sys.argv[2])==0 and len(train)>150000:

        import re
        path_list = glob.glob('../log_submit/0*CV*LB*.csv')
        path_list.append(submit_path)
        #  path_list_2 = glob.glob('../check_submit/*.csv')
        #  path_list += path_list_2

        tmp_list = []
        path_list = list(set(path_list))
        for path in path_list:
            tmp = pd.read_csv(path)
            tmp_path = path.replace(".", '-')
            cv = re.search(r'CV([^/.]*)_LB', tmp_path).group(1).replace('-', '.')
            lb = re.search(r'LB([^/.]*).csv', tmp_path).group(1).replace('-', '.')
            #  if lb<'3.690' and path!=submit_path:
            #      continue
            tmp.rename(columns={'target':f"CV{cv[:9]}_LB{lb}"}, inplace=True)
            tmp.set_index('card_id', inplace=True)
            tmp_list.append(tmp.copy())

        if len(tmp_list)>0:
            df = pd.concat(tmp_list, axis=1)
            df_corr = df.corr(method='pearson')

            logger.info(f'''
#========================================================================
# OUTLIER FIT SCORE: {out_score}
# SUBMIT CORRELATION:
{df_corr[f'CV{str(cv_score)[:9]}_LB'].sort_values()}
#========================================================================''')
except ValueError:
    pass
except TypeError:
    pass
