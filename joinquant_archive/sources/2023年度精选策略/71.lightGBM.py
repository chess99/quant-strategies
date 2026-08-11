#!/usr/bin/env python
# coding: utf-8

# In[1]:


import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn import metrics
from sklearn.metrics import mean_squared_error
from sklearn.metrics import accuracy_score
import joblib
import pydotplus
from sklearn.tree import export_graphviz
from sklearn.model_selection import GridSearchCV
import lightgbm as lgb
from lightgbm import plot_importance
import matplotlib.pyplot as plt
get_ipython().run_line_magic('matplotlib', 'inline')


# In[70]:


file = 'trainData_20211101_all.txt'
with open(file, 'r') as f:
    data =  f.readlines()
print(f'data length = {len(data)}')


# In[71]:


# 全部
codeList = []
train = []
label = []
for line in data[:]:
    tmp = list(line.replace('True', '1').replace('False', '0').replace(' ', '').split(','))
    code = tmp[0].replace('\'', '')
#     codeList.append(code)
    train.append([float(i) for i in tmp[1:-1]])
    label.append(float(tmp[-1]))
#     print(f'tmp={tmp}')

# print(f'codeList={codeList}')
# print(f'label={label}')
# print(f'train={train}')

label_1_thre = 0.03 # 涨幅多少才算上涨的阈值
final_label = [int(i > label_1_thre) for i in label]


# In[29]:


# 创业板
codeList = []
train = []
label = []
for line in data[:]:
    tmp = list(line.replace('True', '1').replace('False', '0').replace(' ', '').split(','))
    code = tmp[0].replace('\'', '')
#     print(f'code={code}')
    if '30' != code[:2]:
        codeList.append(code)
        train.append([float(i) for i in tmp[1:-1]])
        label.append(float(tmp[-1]))
#     print(f'tmp={tmp}')

# print(f'codeList={codeList}')
# print(f'label={label}')
# print(f'train={train}')

label_1_thre = 0.03 # 涨幅多少才算上涨的阈值
final_label = [int(i > label_1_thre) for i in label]


# In[34]:


codeList[:10]


# ### 均分label为1和0的

# In[72]:


len_label_1 = sum(final_label)
len_label_0 = len(final_label) - sum(final_label)
print(f'len_label_1={len_label_1}')
print(f'len_label_0={len_label_0}')
min_num = min(len_label_1, len_label_0)

avg_train = []
avg_label = []
count_0 = 0
count_1 = 0
for i in range(len(final_label)):
    if final_label[i] == 1 and count_1 < min_num:
        avg_train.append(train[i])
        avg_label.append(final_label[i])
        count_1 += 1
    if final_label[i] == 0 and count_0 < min_num:
        avg_train.append(train[i])
        avg_label.append(final_label[i])
        count_0 += 1
print('done')
print(f'now trainSet length = {len(avg_train)}, label length = {len(avg_label)}')


# In[73]:


x_train, x_test, y_train, y_test = train_test_split(avg_train, avg_label, train_size=0.8, random_state=666)
x_train = np.array(x_train)
x_test = np.array(x_test)
y_train = np.array(y_train)
y_test = np.array(y_test)


# In[22]:


x_train[0]


# In[12]:


def get_acc_for_T_F(predict, label):
    sum_1 = 0
    sum_0 = 0
    right_1 = 0
    right_0 = 0
    pred_1 = 0
    real_1 = 0
    pred_0 = 0
    real_0 = 0
    for i in range(len(label)):
        if label[i] == 1:
            sum_1 += 1
            if predict[i] == 1:
                right_1 += 1
        elif label[i] == 0:
            sum_0 += 1
            if predict[i] == 0:
                right_0 += 1
    
    for i in range(len(label)):
        if predict[i] == 1:
            pred_1 += 1
            if label[i] == 1:
                real_1 += 1
        elif predict[i] == 0:
            pred_0 += 1
            if label[i] == 0:
                real_0 += 1
    print(f'right1/sum1={right_1}/{sum_1}={round(right_1/sum_1*100, 2)}%')
    print(f'right0/sum0={right_0}/{sum_0}={round(right_0/sum_0*100, 2)}%')
    if pred_1 > 0:
        print(f'real_1/pred_1={real_1}/{pred_1}={round(real_1/pred_1*100, 2)}%')
        print(f'real_0/pred_0={real_0}/{pred_0}={round(real_0/pred_0*100, 2)}%')
    else:
        print('没有预测为涨的')


# ### Step 1 调整max_depth 和 num_leaves

# In[23]:


# fit时不需要转成gbm的data格式

# 为lightgbm准备Dataset格式数据
# lgb_train = lgb.Dataset(x_train, y_train)
# lgb_eval = lgb.Dataset(x_test, y_test, reference=lgb_train)
parameters = {
    'max_depth': list(range(8, 13, 2),
    'num_leaves': list(range(100, 501, 100)),
}

gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = True,
                         metric = 'binary_logloss,auc',
                         max_depth = 6,
                         num_leaves = 40,
                         learning_rate = 0.1,
                         feature_fraction = 0.7,
                         min_child_samples=21,
                         min_child_weight=0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.001,
                         reg_lambda = 8,
                         cat_smooth = 0,
                         num_iterations = 200,   
                        )

gsearch = GridSearchCV(gbm, param_grid=parameters, scoring='roc_auc', cv=3)

print('Start training...')

gsearch.fit(x_train, y_train)

print('参数的最佳取值:{0}'.format(gsearch.best_params_))
print('最佳模型得分:{0}'.format(gsearch.best_score_))
print(gsearch.cv_results_['mean_test_score'])
print(gsearch.cv_results_['params'])


# ### Step2 调整min_data_in_leaf 和 min_sum_hessian_in_leaf

# In[28]:


parameters = {
    'min_child_samples': list(range(100, 501, 100)),
    'min_child_weight': [0.001, 0.002, 0.003],
}

gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = True,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 0.7,
                         min_child_samples = 21,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.001,
                         reg_lambda = 8,
                         cat_smooth = 0,
                         num_iterations = 200,
                        )
gsearch = GridSearchCV(gbm, param_grid=parameters, scoring='roc_auc', cv=3)
gsearch.fit(x_train, y_train)
print('参数的最佳取值:{0}'.format(gsearch.best_params_))
print('最佳模型得分:{0}'.format(gsearch.best_score_))
print(gsearch.cv_results_['mean_test_score'])
print(gsearch.cv_results_['params'])


# ### Step 3 调整feature_fraction

# In[29]:


parameters = {
    'feature_fraction': [0.6, 0.8, 1],
}

gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = True,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 0.7,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.001,
                         reg_lambda = 8,
                         cat_smooth = 0,
                         num_iterations = 200,
                        )
gsearch = GridSearchCV(gbm, param_grid=parameters, scoring='roc_auc', cv=3)
gsearch.fit(x_train, y_train)
print('参数的最佳取值:{0}'.format(gsearch.best_params_))
print('最佳模型得分:{0}'.format(gsearch.best_score_))
print(gsearch.cv_results_['mean_test_score'])
print(gsearch.cv_results_['params'])


# ### Step 4 调整bagging_fraction和bagging_freq

# In[31]:


parameters = {
     'bagging_fraction': [0.8, 0.9, 1],
     'bagging_freq': [1, 2, 3],
}
gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = True,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.001,
                         reg_lambda = 8,
                         cat_smooth = 0,
                         num_iterations = 350,
                        )
gsearch = GridSearchCV(gbm, param_grid=parameters, scoring='roc_auc', cv=3)
gsearch.fit(x_train, y_train)
print('参数的最佳取值:{0}'.format(gsearch.best_params_))
print('最佳模型得分:{0}'.format(gsearch.best_score_))
print(gsearch.cv_results_['mean_test_score'])
print(gsearch.cv_results_['params'])


# ### Step 5 调整lambda_l1(reg_alpha)和lambda_l2(reg_lambda)

# In[40]:


# tune reg_alpha
parameters = {
    'reg_alpha': [1e-5, 1e-2, 0.1, 1, 100, 1000],
    'reg_lambda': [1e-5, 1e-2, 0.1, 1, 100, 1000],
}

gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = True,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.001,
                         reg_lambda = 8,
                         cat_smooth = 0,
                         num_iterations = 350,
                        )
gsearch = GridSearchCV(gbm, param_grid=parameters, scoring='roc_auc', cv=3)
gsearch.fit(x_train, y_train)
print('参数的最佳取值:{0}'.format(gsearch.best_params_))
print('最佳模型得分:{0}'.format(gsearch.best_score_))
print(gsearch.cv_results_['mean_test_score'])
print(gsearch.cv_results_['params'])


# ### Step 6 调整cat_smooth

# In[41]:


parameters = {
     'cat_smooth': [0,5,10],
}

gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = True,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.1,
                         reg_lambda = 100,
                         cat_smooth = 0,
                         num_iterations = 350,
                        )
gsearch = GridSearchCV(gbm, param_grid=parameters, scoring='roc_auc', cv=3)
gsearch.fit(x_train, y_train)
print('参数的最佳取值:{0}'.format(gsearch.best_params_))
print('最佳模型得分:{0}'.format(gsearch.best_score_))
print(gsearch.cv_results_['mean_test_score'])
print(gsearch.cv_results_['params'])


# ### Step 7 最后，适当调小learning_rate的值以及调整num_iterations的大小

# In[13]:


gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = False,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.1,
                         reg_lambda = 100,
                         cat_smooth = 0,
                         num_iterations = 350,
                        )

gbm.fit(x_train, y_train)

y_train_pred_prob = gbm.predict(x_train)
y_test_pred_prob = gbm.predict(x_test) # predict返回的是概率
train_accuracy = accuracy_score(y_train, y_train_pred_prob)
test_accuracy = accuracy_score(y_test, y_test_pred_prob)

train_auc_score = metrics.roc_auc_score(y_train, y_train_pred_prob)
test_auc_score = metrics.roc_auc_score(y_test, y_test_pred_prob)
print(f'train_accuracy accuarcy = {round(train_accuracy*100, 2)}, AUC={train_auc_score}')
print(f'test_accuracy accuarcy = {round(test_accuracy*100, 2)}, AUC={test_auc_score}')
# GBDT result:
# acc_train=69.98%
# acc_test=63.97%
# auc score=0.6396242183762156


# ### 试一试更大的num_iterations和GBDT比较，明显优于GBDT

# ### Step1 全市场

# In[17]:


gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = False,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.1,
                         reg_lambda = 100,
                         cat_smooth = 0,
                         num_iterations = 1500,
                        )

gbm.fit(x_train, y_train)

y_train_pred_prob = gbm.predict(x_train)
y_test_pred_prob = gbm.predict(x_test) # predict返回的是概率
train_accuracy = accuracy_score(y_train, y_train_pred_prob)
test_accuracy = accuracy_score(y_test, y_test_pred_prob)

train_auc_score = metrics.roc_auc_score(y_train, y_train_pred_prob)
test_auc_score = metrics.roc_auc_score(y_test, y_test_pred_prob)
print(f'train_accuracy accuarcy = {round(train_accuracy*100, 2)}, AUC={train_auc_score}')
print(f'test_accuracy accuarcy = {round(test_accuracy*100, 2)}, AUC={test_auc_score}')
# GBDT result:
# acc_train=69.98%
# acc_test=63.97%
# auc score=0.6396242183762156


# In[ ]:


# best result
train_accuracy accuarcy = 83.94, AUC=0.8393293702744625
test_accuracy accuarcy = 79.2, AUC=0.7921258363079904


# ### 保存模型

# In[19]:


import pickle
with open('gbm_model_v1_all.pkl','wb') as fw:
    pickle.dump(gbm, fw)


# ### 分析因子

# In[ ]:


up_num_ratio, get_high_limit_num_40_days, _close_max_index, get_rise_num_40_days, macd_1_day,
macd_2_day, macd_3_day, compare_early_low, rise_before, withdraw, low_3_days_std, volume_min


# In[18]:


print('Feature names:', gbm.booster_.feature_name())
# feature importances
print('Feature importances:', list(gbm.booster_.feature_importance()))
plot_importance(gbm, max_num_features=13)
plt.show()


# ### Step2 创业板

# In[26]:


gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = False,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.1,
                         reg_lambda = 100,
                         cat_smooth = 0,
                         num_iterations = 1500,
                        )

gbm.fit(x_train, y_train)

y_train_pred_prob = gbm.predict(x_train)
y_test_pred_prob = gbm.predict(x_test) # predict返回的是概率
train_accuracy = accuracy_score(y_train, y_train_pred_prob)
test_accuracy = accuracy_score(y_test, y_test_pred_prob)

train_auc_score = metrics.roc_auc_score(y_train, y_train_pred_prob)
test_auc_score = metrics.roc_auc_score(y_test, y_test_pred_prob)
print(f'train_accuracy accuarcy = {round(train_accuracy*100, 2)}, AUC={train_auc_score}')
print(f'test_accuracy accuarcy = {round(test_accuracy*100, 2)}, AUC={test_auc_score}')
# GBDT result:
# acc_train=69.98%
# acc_test=63.97%
# auc score=0.6396242183762156


# In[ ]:


# best result
train_accuracy accuarcy = 84.73, AUC=0.847246889672648
test_accuracy accuarcy = 77.95, AUC=0.7795080117245465

#样本不均衡的时候，结果就不准了
#train_accuracy accuarcy = 75.7, AUC=0.7561205536005607
# test_accuracy accuarcy = 69.82, AUC=0.6742857512229079


# ### 保存模型

# In[27]:


import pickle
with open('gbm_model_v1_cyb.pkl','wb') as fw:
    pickle.dump(gbm, fw)


# In[ ]:


up_num_ratio, get_high_limit_num_40_days, _close_max_index, get_rise_num_40_days, macd_1_day,
macd_2_day, macd_3_day, compare_early_low, rise_before, withdraw, low_3_days_std, volume_min


# In[33]:


print('Feature names:', gbm.booster_.feature_name())
# feature importances
print('Feature importances:', list(gbm.booster_.feature_importance()))
plot_importance(gbm, max_num_features=13)
plt.show()


# #### 创业板的column8: rise_before比横盘缩量更重要，符合常理

# ### Step3 主板

# In[37]:


gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = False,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.1,
                         reg_lambda = 100,
                         cat_smooth = 0,
                         num_iterations = 1500,
                        )

gbm.fit(x_train, y_train)

y_train_pred_prob = gbm.predict(x_train)
y_test_pred_prob = gbm.predict(x_test) # predict返回的是概率
train_accuracy = accuracy_score(y_train, y_train_pred_prob)
test_accuracy = accuracy_score(y_test, y_test_pred_prob)

train_auc_score = metrics.roc_auc_score(y_train, y_train_pred_prob)
test_auc_score = metrics.roc_auc_score(y_test, y_test_pred_prob)
print(f'train_accuracy accuarcy = {round(train_accuracy*100, 2)}, AUC={train_auc_score}')
print(f'test_accuracy accuarcy = {round(test_accuracy*100, 2)}, AUC={test_auc_score}')
# GBDT result:
# acc_train=69.98%
# acc_test=63.97%
# auc score=0.6396242183762156


# In[ ]:


# best result
train_accuracy accuarcy = 85.51, AUC=0.8550871618873747
test_accuracy accuarcy = 80.6, AUC=0.8060911534064704


# ### 保存模型

# In[38]:


import pickle
with open('gbm_model_v1_zb.pkl','wb') as fw:
    pickle.dump(gbm, fw)


# In[ ]:


up_num_ratio, get_high_limit_num_40_days, _close_max_index, get_rise_num_40_days, macd_1_day,
macd_2_day, macd_3_day, compare_early_low, rise_before, withdraw, low_3_days_std, volume_min


# In[39]:


print('Feature names:', gbm.booster_.feature_name())
# feature importances
print('Feature importances:', list(gbm.booster_.feature_importance()))
plot_importance(gbm, max_num_features=13)
plt.show()


# #### 主板的importance和全市场的差不多

# ### 不均衡样本

# In[42]:


gbm = lgb.LGBMClassifier(objective = 'binary',
                         is_unbalance = True,
                         metric = 'binary_logloss,auc',
                         max_depth = 10,
                         num_leaves = 200,
                         learning_rate = 0.1,
                         feature_fraction = 1.0,
                         min_child_samples = 200,
                         min_child_weight = 0.001,
                         bagging_fraction = 1,
                         bagging_freq = 2,
                         reg_alpha = 0.1,
                         reg_lambda = 100,
                         cat_smooth = 0,
                         num_iterations = 1500,
                        )

gbm.fit(x_train, y_train)

y_train_pred_prob = gbm.predict(x_train)
y_test_pred_prob = gbm.predict(x_test) # predict返回的是概率
train_accuracy = accuracy_score(y_train, y_train_pred_prob)
test_accuracy = accuracy_score(y_test, y_test_pred_prob)

train_auc_score = metrics.roc_auc_score(y_train, y_train_pred_prob)
test_auc_score = metrics.roc_auc_score(y_test, y_test_pred_prob)
print(f'train_accuracy accuarcy = {round(train_accuracy*100, 2)}, AUC={train_auc_score}')
print(f'test_accuracy accuarcy = {round(test_accuracy*100, 2)}, AUC={test_auc_score}')
# GBDT result:
# acc_train=69.98%
# acc_test=63.97%
# auc score=0.6396242183762156


# In[43]:


import pickle
with open('gbm_model_v1_unbalanced.pkl','wb') as fw:
    pickle.dump(gbm, fw)


# In[44]:


print('Feature names:', gbm.booster_.feature_name())
# feature importances
print('Feature importances:', list(gbm.booster_.feature_importance()))
plot_importance(gbm, max_num_features=13)
plt.show()


# #### predict

# In[68]:


pkl_file = open('gbm_model_v1_unbalanced.pkl', 'rb')
gbm2 = pickle.load(pkl_file)


# In[78]:


a = [0.7759632559326359, 0, 17, 19, 0.10538924425524246, 0.0350440323241728, -0.05272956547902799, 1.120431396045536, 1.1670547147846333, 0.9645885286783042, 0.007826915650659601, 1.1215344438862391]
gbm2.predict([a], raw_score=True)


# In[63]:


gbm.predict([a])


# ### 可以early stop的，适合随着市场在线学习

# In[74]:


params = {'objective' : 'binary',
        'is_unbalance' : False,
        'metric' : 'l2,auc',
        'max_depth' : 10,
        'num_leaves' : 200,
        'learning_rate' : 0.1,
        'feature_fraction' : 1.0,
        'min_child_samples' : 200,
        'min_child_weight' : 0.001,
        'bagging_fraction' : 1,
        'bagging_freq' : 2,
        'reg_alpha' : 0.1,
        'reg_lambda' : 100,
        'cat_smooth' : 0,
        'num_iterations' : 1500,
}

lgb_train = lgb.Dataset(x_train, y_train) # 将数据保存到LightGBM二进制文件将使加载更快
lgb_eval = lgb.Dataset(x_test, y_test, reference=lgb_train)  # 创建验证数据

gbm = lgb.train(params, lgb_train,num_boost_round=20,valid_sets=lgb_eval,early_stopping_rounds=5)
# gbm.fit(x_train, y_train)

y_train_pred_prob = gbm.predict(x_train)
y_test_pred_prob = gbm.predict(x_test) # predict返回的是概率
# train_accuracy = accuracy_score(y_train, y_train_pred_prob)
# test_accuracy = accuracy_score(y_test, y_test_pred_prob)

train_auc_score = metrics.roc_auc_score(y_train, y_train_pred_prob)
test_auc_score = metrics.roc_auc_score(y_test, y_test_pred_prob)
print(f'train AUC={train_auc_score}')
print(f'test AUC={test_auc_score}')

# train AUC=0.8927500554518755
# test AUC=0.8709485082515903


# In[75]:


import pickle
with open('gbm_train_model_v2_all.pkl','wb') as fw:
    pickle.dump(gbm, fw)


# In[ ]:





# ### 根据不同阈值观察TP/TN

# In[29]:


# gbr = GradientBoostingClassifier(n_estimators=650, max_depth=9, min_samples_split=1400, min_samples_leaf=90,\
#                                  max_features=11, learning_rate=0.1, subsample=0.75, random_state=666)
# gbr.fit(x_train, y_train)
# joblib.dump(gbr, f'model_n_6500_depth_9_max_features_9_min_samples_split_1200_sample_leaf_70_lr_0.01_sample_0.75.m')# 保存模型

y_gbr = gbm.predict(x_train)
y_gbr1 = gbm.predict(x_test)
auc_score = metrics.roc_auc_score(y_test, y_gbr1)

print(f'auc score={auc_score}')

print('for train:')
get_acc_for_T_F(y_gbr>0.5, y_train)
print('for test:')
get_acc_for_T_F(y_gbr1>0.5, y_test)

# 调参前的结果
# acc_train=60.88%
# acc_test=60.98%
# auc score=0.6096141776126576
# for train:
# right1/sum1=95227/136969=69.52%
# right0/sum0=71648/137141=52.24%
# real_1/pred_1=95227/160720=59.25%
# real_0/pred_0=71648/113390=63.19%
# for test:
# right1/sum1=23808/34350=69.31%
# right0/sum0=17982/34178=52.61%
# real_1/pred_1=23808/40004=59.51%
# real_0/pred_0=17982/28524=63.04%


# In[31]:


# 调参结束后，0.7阈值可以达到综合80%+的准确率，且操作次数并不低；0.8阈值就可以达到综合90%+的正确率了，相比调参前大幅提升
for thre in np.arange(0.5, 0.8, 0.05):
    y_gbr_by_prob = y_gbr > thre
    y_gbr1_by_prob = y_gbr1 > thre
    print('- ' * 20 + f'thre = {round(thre, 2)}' + ' -' * 20)
    print('for train:')
    get_acc_for_T_F(y_gbr_by_prob, y_train)
    print('for test:')
    get_acc_for_T_F(y_gbr1_by_prob, y_test)

