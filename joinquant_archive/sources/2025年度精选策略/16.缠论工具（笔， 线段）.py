#!/usr/bin/env python
# coding: utf-8

# In[1]:


import numpy as np
import copy
import talib

from enum import Enum 

from numpy.lib.recfunctions import append_fields
from scipy.ndimage.interpolation import shift

class InclusionType(Enum):
    # output: 0 = no inclusion, 1 = first contains second, 2 second contains first
    noInclusion = 0
    firstCsecond = 2
    secondCfirst = 3
    
class TopBotType(Enum):
    noTopBot = 0
    bot2top = 0.5
    top = 1
    top2bot = -0.5
    bot = -1

    @classmethod
    def reverse(cls, tp):
        if tp == cls.top:
            return cls.bot
        elif tp == cls.bot:
            return cls.top
        elif tp == cls.top2bot:
            return cls.bot2top
        elif tp == cls.bot2top:
            return cls.top2bot
        else:
            return cls.noTopBot
    
    @classmethod
    def value2type(cls, val):
        if val == 0:
            return cls.noTopBot
        elif val == 0.5:
            return cls.bot2top
        elif val == 1:
            return cls.top
        elif val == -0.5:
            return cls.top2bot
        elif val == -1:
            return cls.bot
        else:
            return cls.noTopBot


######################## common method ###############################

def float_less(a, b):
    return a < b and not np.isclose(a, b)

def float_more(a, b):
    return a > b and not np.isclose(a, b)

def float_less_equal(a, b):
    return a < b or np.isclose(a, b)

def float_more_equal(a, b):
    return a > b or np.isclose(a, b)

######################## kBarprocessor #############################
GOLDEN_RATIO = 0.618
MIN_PRICE_UNIT=0.01
        
FEN_BI_COLUMNS = ['date', 'close', 'high', 'low', 'tb', 'real_loc']
FEN_DUAN_COLUMNS =  ['date', 'close', 'high', 'low', 'chan_price', 'tb', 'xd_tb', 'real_loc']

def gap_range_func(a):
    if float_more(a['low'] - a['high_s1'], MIN_PRICE_UNIT):
        return [a['high_s1'], a['low']]
    elif float_less(a['high'] - a['low_s1'], -MIN_PRICE_UNIT):
        return [a['high'], a['low_s1']]
    else:
        return [0, 0]

def get_previous_loc(loc, working_df):
    i = loc - 1
    while i >= 0:
        if working_df[i]['tb'] == TopBotType.top.value or working_df[i]['tb'] == TopBotType.bot.value:
            return i
        else:
            i = i - 1
    return None

def get_next_loc(loc, working_df):
    i = loc + 1
    while i < len(working_df):
        if working_df[i]['tb'] == TopBotType.top.value or working_df[i]['tb'] == TopBotType.bot.value:
            return i
        else:
            i = i + 1
    return None


# In[2]:


class KBarChan(object):
    '''
    This is a rewrite of KBarProcessor, that one is too slow!! we used pandas dataframe, we should use numpy array!
    df=False flag is used here
    '''
    
    def __init__(self, kDf, isdebug=False, clean_standardzed=False):
        self.isdebug = isdebug
        self.clean_standardzed = clean_standardzed
        self.kDataFrame_origin = kDf
        self.kDataFrame_standardized = copy.deepcopy(kDf)
        
        self.kDataFrame_standardized = append_fields(self.kDataFrame_standardized, 
                                                     ['new_high', 'new_low', 'trend_type', 'real_loc'],
                                                     [
                                                         [0]*len(self.kDataFrame_standardized),
                                                         [0]*len(self.kDataFrame_standardized),
                                                         [TopBotType.noTopBot.value]*len(self.kDataFrame_standardized),
                                                         [i for i in range(len(self.kDataFrame_standardized))]
                                                     ],
                                                     [float, float, int, int],
                                                     usemask=False)
        self.kDataFrame_marked = None
        self.kDataFrame_xd = None
        self.gap_XD = []
        self.previous_skipped_idx = []
        self.previous_with_xd_gap = False # help to check current gap as XD
        if self.isdebug:
            print("self.kDataFrame_origin head:{0}".format(self.kDataFrame_origin[:10]))
            print("self.kDataFrame_origin tail:{0}".format(self.kDataFrame_origin[-10:]))
        
    def checkInclusive(self, first, second):
        # output: 0 = no inclusion, 1 = first contains second, 2 second contains first
        isInclusion = InclusionType.noInclusion
        first_high = first['high'] if first['new_high']==0 else first['new_high']
        second_high = second['high'] if second['new_high']==0 else second['new_high']
        first_low = first['low'] if first['new_low']==0 else first['new_low']
        second_low = second['low'] if second['new_low']==0 else second['new_low']
        
        if float_less_equal(first_high, second_high) and float_more_equal(first_low, second_low):
            isInclusion = InclusionType.firstCsecond
        elif float_more_equal(first_high, second_high) and float_less_equal(first_low, second_low):
            isInclusion = InclusionType.secondCfirst
        return isInclusion
    
    def isBullType(self, first, second): 
        # this is assuming first second aren't inclusive
        f_high = first['high'] if first['new_high']==0 else first['new_high']
        s_high = second['high'] if second['new_high']==0 else second['new_high']
        return TopBotType.bot2top if float_less(f_high, s_high) else TopBotType.top2bot
            
        
    def standardize(self, initial_state=TopBotType.noTopBot):
        # 1. We need to make sure we start with first two K-bars without inclusive relationship
        # drop the first if there is inclusion, and check again
        if initial_state == TopBotType.top or initial_state == TopBotType.bot:
            # given the initial state, make the first two bars non-inclusive, 
            # the first bar is confirmed as pivot, anything followed with inclusive relation 
            # will be merged into the first bar
            while len(self.kDataFrame_standardized) > 2:
                first_Elem = self.kDataFrame_standardized[0]
                second_Elem = self.kDataFrame_standardized[1]
                if self.checkInclusive(first_Elem, second_Elem) != InclusionType.noInclusion:
                    if initial_state == TopBotType.bot:
                        self.kDataFrame_standardized[0]['new_high'] = second_Elem['high']
                        self.kDataFrame_standardized[0]['new_low'] = first_Elem['low']
                    elif initial_state == TopBotType.top:
                        self.kDataFrame_standardized[0]['new_high'] = first_Elem['high']
                        self.kDataFrame_standardized[0]['new_low'] = second_Elem['low']
                    self.kDataFrame_standardized=np.delete(self.kDataFrame_standardized, 1, axis=0)
                else:
                    self.kDataFrame_standardized[0]['new_high'] = first_Elem['high']
                    self.kDataFrame_standardized[0]['new_low'] = first_Elem['low']
                    break                    
        else:
            while len(self.kDataFrame_standardized) > 2:
                first_Elem = self.kDataFrame_standardized[0]
                second_Elem = self.kDataFrame_standardized[1]
                if self.checkInclusive(first_Elem, second_Elem) != InclusionType.noInclusion:
                    self.kDataFrame_standardized=np.delete(self.kDataFrame_standardized, 0, axis=0)
                else:
                    self.kDataFrame_standardized[0]['new_high'] = first_Elem['high']
                    self.kDataFrame_standardized[0]['new_low'] = first_Elem['low']
                    break


        # 2. loop through the whole data set and process inclusive relationship
        pastElemIdx = 0
        firstElemIdx = pastElemIdx+1
        secondElemIdx = firstElemIdx+1
        high='high'
        low='low'
        new_high = 'new_high'
        new_low = 'new_low'
        trend_type = 'trend_type'
        
        while secondElemIdx < len(self.kDataFrame_standardized): # xrange
            pastElem = self.kDataFrame_standardized[pastElemIdx]
            firstElem = self.kDataFrame_standardized[firstElemIdx]
            secondElem = self.kDataFrame_standardized[secondElemIdx]
            inclusion_type = self.checkInclusive(firstElem, secondElem)
            if inclusion_type != InclusionType.noInclusion:
                trend = firstElem[trend_type] if firstElem[trend_type]!=TopBotType.noTopBot.value else self.isBullType(pastElem, firstElem).value
                compare_func = max if np.isclose(trend, TopBotType.bot2top.value) else min
                if inclusion_type == InclusionType.firstCsecond:
                    self.kDataFrame_standardized[secondElemIdx][new_high]=compare_func(firstElem[high] if firstElem[new_high]==0 else firstElem[new_high], secondElem[high] if secondElem[new_high]==0 else secondElem[new_high])
                    self.kDataFrame_standardized[secondElemIdx][new_low]=compare_func(firstElem[low] if firstElem[new_low]==0 else firstElem[new_low], secondElem[low] if secondElem[new_low]==0 else secondElem[new_low])
                    self.kDataFrame_standardized[secondElemIdx][trend_type] = trend
                    self.kDataFrame_standardized[firstElemIdx][new_high]=0
                    self.kDataFrame_standardized[firstElemIdx][new_low]=0
                    ############ manage index for next round ###########
                    firstElemIdx = secondElemIdx
                    secondElemIdx += 1
                else:
                    self.kDataFrame_standardized[firstElemIdx][new_high]=compare_func(firstElem[high] if firstElem[new_high]==0 else firstElem[new_high], secondElem[high] if secondElem[new_high]==0 else secondElem[new_high])
                    self.kDataFrame_standardized[firstElemIdx][new_low]=compare_func(firstElem[low] if firstElem[new_low]==0 else firstElem[new_low], secondElem[low] if secondElem[new_low]==0 else secondElem[new_low])                        
                    self.kDataFrame_standardized[firstElemIdx][trend_type]=trend
                    self.kDataFrame_standardized[secondElemIdx][new_high]=0
                    self.kDataFrame_standardized[secondElemIdx][new_low]=0
                    ############ manage index for next round ###########
                    secondElemIdx += 1
            else:
                if firstElem[new_high] == 0: 
                    self.kDataFrame_standardized[firstElemIdx][new_high] = firstElem[high]
                if firstElem[new_low] == 0: 
                    self.kDataFrame_standardized[firstElemIdx][new_low] = firstElem[low]
                if secondElem[new_high] == 0: 
                    self.kDataFrame_standardized[secondElemIdx][new_high] = secondElem[high]
                if secondElem[new_low] == 0: 
                    self.kDataFrame_standardized[secondElemIdx][new_low] = secondElem[low]
                ############ manage index for next round ###########
                pastElemIdx = firstElemIdx
                firstElemIdx = secondElemIdx
                secondElemIdx += 1
                
        # clean up
        self.kDataFrame_standardized[high] = self.kDataFrame_standardized[new_high]
        self.kDataFrame_standardized[low] = self.kDataFrame_standardized[new_low]
        self.kDataFrame_standardized=self.kDataFrame_standardized[['date', 'close', 'high', 'low', 'real_loc']]

        # remove standardized kbars
        self.kDataFrame_standardized = self.kDataFrame_standardized[self.kDataFrame_standardized['high']!=0]

        # new index add for later distance calculation => straight after standardization
        self.kDataFrame_standardized = append_fields(self.kDataFrame_standardized, 
                                                     'new_index',
                                                     [i for i in range(len(self.kDataFrame_standardized))],
                                                     usemask=False)
        return self.kDataFrame_standardized
    
    def checkTopBot(self, current, first, second):
        if float_more(first['high'], current['high']) and float_more(first['high'], second['high']):
            return TopBotType.top
        elif float_less(first['low'], current['low']) and float_less(first['low'], second['low']):
            return TopBotType.bot
        else:
            return TopBotType.noTopBot
    
    def markTopBot(self, initial_state=TopBotType.noTopBot):
        self.kDataFrame_standardized = append_fields(self.kDataFrame_standardized,
                                                     'tb',
                                                     [TopBotType.noTopBot.value]*self.kDataFrame_standardized.size,
                                                     usemask=False
                                                     )
        if self.kDataFrame_standardized.size < 7:
            return
        tb = 'tb'
        if initial_state == TopBotType.top or initial_state == TopBotType.bot:
            felem = self.kDataFrame_standardized[0]
            selem = self.kDataFrame_standardized[1]
            if (initial_state == TopBotType.top and float_more_equal(felem['high'], selem['high'])) or                 (initial_state == TopBotType.bot and float_less_equal(felem['low'], selem['low'])):
                self.kDataFrame_standardized[0][tb] = initial_state.value
            else:
                if self.isdebug:
                    print("Incorrect initial state given!!!")
                
        # This function assume we have done the standardization process (no inclusion)
        last_idx = 0
        for idx in range(self.kDataFrame_standardized.size-2): #xrange
            currentElem = self.kDataFrame_standardized[idx]
            firstElem = self.kDataFrame_standardized[idx+1]
            secondElem = self.kDataFrame_standardized[idx+2]
            topBotType = self.checkTopBot(currentElem, firstElem, secondElem)
            if topBotType != TopBotType.noTopBot:
                self.kDataFrame_standardized[idx+1][tb] = topBotType.value
                last_idx = idx+1
                
        # mark the first kbar
        if (self.kDataFrame_standardized[0][tb] != TopBotType.top.value and            self.kDataFrame_standardized[0][tb] != TopBotType.bot.value):
            first_loc = get_next_loc(0, self.kDataFrame_standardized)
            if first_loc is not None:
                first_tb = TopBotType.value2type(self.kDataFrame_standardized[first_loc][tb])
                self.kDataFrame_standardized[0][tb] = TopBotType.reverse(first_tb).value
            
        # mark the last kbar 
        last_tb = TopBotType.value2type(self.kDataFrame_standardized[last_idx][tb])
        self.kDataFrame_standardized[-1][tb] = TopBotType.reverse(last_tb).value
        if self.isdebug:
            print("mark topbot on self.kDataFrame_standardized[20]:{0}".format(self.kDataFrame_standardized[:20]))
            
    def trace_back_index(self, working_df, previous_index):
        # find the closest FenXing with top/bot backwards from previous_index
        idx = previous_index-1
        while idx >= 0:
            fx = working_df[idx]
            if fx['tb'] == TopBotType.noTopBot.value:
                idx -= 1
                continue
            else:
                return idx
        if self.isdebug:
            print("We don't have previous valid FenXing")
        return None
    
    def prepare_original_kdf(self):
        if 'macd' not in self.kDataFrame_origin.dtype.names:
            _, _, macd = talib.MACD(self.kDataFrame_origin['close'])
            macd[np.isnan(macd)] = 0
            self.kDataFrame_origin = append_fields(self.kDataFrame_origin,
                                                    'macd',
                                                    macd,
                                                    float,
                                                    usemask=False)

    def gap_exists_in_range(self, start_idx, end_idx): # end_idx included
        # no need to drop first row, simple don't use = 
        gap_working_df = self.kDataFrame_origin[(start_idx < self.kDataFrame_origin['date']) & (self.kDataFrame_origin['date'] <= end_idx)]
        
        # drop the first row, as we only need to find gaps from start_idx(non-inclusive) to end_idx(inclusive)  
#         gap_working_df = np.delete(gap_working_df, 0, axis=0)
        return np.any(gap_working_df['gap']!=0)
    
    
    def gap_exists(self):
        high_shift = shift(self.kDataFrame_origin['high'], 1, cval=0)
        low_shift = shift(self.kDataFrame_origin['low'], 1, cval=0)
        self.kDataFrame_origin = append_fields(self.kDataFrame_origin,
                                               ['gap', 'high_shift', 'low_shift', 'gap_range_start', 'gap_range_end'],
                                               [
                                                   [0]*self.kDataFrame_origin.size,
                                                   high_shift,
                                                   low_shift,
                                                   [0]*self.kDataFrame_origin.size,
                                                   [0]*self.kDataFrame_origin.size
                                               ],
                                               [int, float, float, float, float],
                                               usemask=False)
        
        i = 0
        while i < self.kDataFrame_origin.size:
            item = self.kDataFrame_origin[i]
            if float_more(item['low'] - item['high_shift'], MIN_PRICE_UNIT): # upwards gap
                self.kDataFrame_origin[i]['gap'] = 1
                self.kDataFrame_origin[i]['gap_range_start'] = item['high_shift']
                self.kDataFrame_origin[i]['gap_range_end'] = item['low']
            elif float_less(item['high'] - item['low_shift'], -MIN_PRICE_UNIT): # downwards gap
                self.kDataFrame_origin[i]['gap'] = -1
                self.kDataFrame_origin[i]['gap_range_start'] = item['high']
                self.kDataFrame_origin[i]['gap_range_end'] = item['low_shift']
            i = i + 1
        
#         self.kDataFrame_origin = self.kDataFrame_origin[FEN_BI_COLUMNS + ['gap', 'gap_range_start', 'gap_range_end']]
#         if self.isdebug:
#             print(self.kDataFrame_origin[self.kDataFrame_origin['gap']])
    
    def gap_region(self, start_idx, end_idx, direction=TopBotType.noTopBot):
        # no need to drop first row, simple don't use = 
        gap_working_df = self.kDataFrame_origin[(start_idx < self.kDataFrame_origin['date']) & (self.kDataFrame_origin['date'] <= end_idx)]
        if direction == TopBotType.noTopBot:
            return gap_working_df[gap_working_df['gap']!=0][['gap_range_start', 'gap_range_end']].tolist()
        elif direction == TopBotType.top2bot:
            return gap_working_df[gap_working_df['gap']==-1][['gap_range_start', 'gap_range_end']].tolist()
        elif direction == TopBotType.bot2top:
            return gap_working_df[gap_working_df['gap']==1][['gap_range_start', 'gap_range_end']].tolist()

    def get_next_tb(self, idx, working_df):
        '''
        give the next loc from current idx(excluded) if overflow return size of working_df
        '''
        i = idx+1
        while i < working_df.size:
            if working_df[i]['tb'] == TopBotType.top.value or working_df[i]['tb'] == TopBotType.bot.value:
                break
            i += 1
        return i

    def clean_first_two_tb(self, working_df):
        ############################# make sure the first two Ding/Di are valid to start with ###########################
        firstIdx = 0
        secondIdx= firstIdx+1
        thirdIdx = secondIdx+1
        tb = 'tb'
        high = 'high'
        low = 'low'
        new_index = 'new_index'

        while thirdIdx is not None and thirdIdx < working_df.size:
            firstFenXing = working_df[firstIdx]
            secondFenXing = working_df[secondIdx]
            thirdFenXing = working_df[thirdIdx]
            if firstFenXing[tb] == secondFenXing[tb] == TopBotType.top.value and float_less(firstFenXing[high], secondFenXing[high]):
                working_df[firstIdx][tb] = TopBotType.noTopBot.value
                firstIdx = get_next_loc(firstIdx, working_df)
                secondIdx=get_next_loc(firstIdx, working_df)
                thirdIdx=get_next_loc(secondIdx, working_df)
                continue
            elif firstFenXing[tb] == secondFenXing[tb] == TopBotType.top.value and float_more_equal(firstFenXing[high], secondFenXing[high]):
                working_df[secondIdx][tb] = TopBotType.noTopBot.value
                secondIdx = get_next_loc(secondIdx, working_df)
                thirdIdx=get_next_loc(secondIdx, working_df)
                continue
            elif firstFenXing[tb] == secondFenXing[tb] == TopBotType.bot.value and float_more(firstFenXing[low], secondFenXing[low]):
                working_df[firstIdx][tb] = TopBotType.noTopBot.value
                firstIdx = get_next_loc(firstIdx, working_df)
                secondIdx=get_next_loc(firstIdx, working_df)
                thirdIdx=get_next_loc(secondIdx, working_df)
                continue
            elif firstFenXing[tb] == secondFenXing[tb] == TopBotType.bot.value and float_less_equal(firstFenXing[low], secondFenXing[low]):
                working_df[secondIdx][tb] = TopBotType.noTopBot.value
                secondIdx = get_next_loc(secondIdx, working_df)
                thirdIdx=get_next_loc(secondIdx, working_df)
                continue
            elif secondFenXing[new_index] - firstFenXing[new_index] < 4:
                if firstFenXing[tb] == thirdFenXing[tb] == TopBotType.top.value and float_less(firstFenXing[high], thirdFenXing[high]):
                    working_df[firstIdx][tb] = TopBotType.noTopBot.value
                    firstIdx = get_next_loc(firstIdx, working_df)
                    secondIdx=get_next_loc(firstIdx, working_df)
                    thirdIdx=get_next_loc(secondIdx, working_df)
                    continue
                elif firstFenXing[tb] == thirdFenXing[tb] == TopBotType.top.value and float_more_equal(firstFenXing[high], thirdFenXing[high]):
                    working_df[secondIdx][tb] = TopBotType.noTopBot.value
                    secondIdx=get_next_loc(secondIdx, working_df)
                    thirdIdx=get_next_loc(secondIdx, working_df)
                    continue
                elif firstFenXing[tb] == thirdFenXing[tb] == TopBotType.bot.value and float_more(firstFenXing[low], thirdFenXing[low]):
                    working_df[firstIdx][tb] = TopBotType.noTopBot.value
                    firstIdx = get_next_loc(firstIdx, working_df)
                    secondIdx=get_next_loc(firstIdx, working_df)
                    thirdIdx=get_next_loc(secondIdx, working_df)
                    continue
                elif firstFenXing[tb] == thirdFenXing[tb] == TopBotType.bot.value and float_less_equal(firstFenXing[low], thirdFenXing[low]):
                    working_df[secondIdx][tb] = TopBotType.noTopBot.value
                    secondIdx=get_next_loc(secondIdx, working_df)
                    thirdIdx=get_next_loc(secondIdx, working_df)
                    continue
                else:
                    print("somthing WRONG!")
                    return
                    
            elif firstFenXing[tb] == TopBotType.top.value and secondFenXing[tb] == TopBotType.bot.value and float_less_equal(firstFenXing[high], secondFenXing[low]):
                working_df[firstIdx][tb] = TopBotType.noTopBot.value
                working_df[secondIdx][tb] = TopBotType.noTopBot.value
                firstIdx = get_next_loc(firstIdx, working_df)
                secondIdx=get_next_loc(firstIdx, working_df)
                thirdIdx=get_next_loc(secondIdx, working_df)
                continue
            elif firstFenXing[tb] == TopBotType.bot.value and secondFenXing[tb] == TopBotType.top.value and float_more_equal(firstFenXing[low], secondFenXing[high]):
                working_df[firstIdx][tb] = TopBotType.noTopBot.value
                working_df[secondIdx][tb] = TopBotType.noTopBot.value
                firstIdx = get_next_loc(firstIdx, working_df)
                secondIdx=get_next_loc(firstIdx, working_df)
                thirdIdx=get_next_loc(secondIdx, working_df)
                continue
            else:
                break
 
        working_df = working_df[working_df[tb]!=TopBotType.noTopBot.value]
        return working_df
        
    def check_gap_qualify(self, working_df, previous_index, current_index, next_index):
        # possible BI status 1 check top high > bot low 2 check more than 3 bars (strict BI) in between
        # under this section of code we expect there are no two adjacent fenxings with the same status
        gap_qualify = False
        if self.gap_exists_in_range(working_df[current_index]['date'], working_df[next_index]['date']):
            gap_direction = TopBotType.bot2top if working_df[next_index]['tb'] == TopBotType.top.value else                            TopBotType.top2bot if working_df[next_index]['tb'] == TopBotType.bot.value else                            TopBotType.noTopBot
            gap_ranges = self.gap_region(working_df[current_index]['date'], working_df[next_index]['date'], gap_direction)
            gap_ranges = self.combine_gaps(gap_ranges)
            for gap in gap_ranges:
                if previous_index is None:
                    return True
                    
                if working_df[previous_index]['tb'] == TopBotType.top.value: 
                    #gap higher than previous high
                    gap_qualify = float_less(gap[0], working_df[previous_index]['low']) and                                  float_less_equal(working_df[previous_index]['low'], working_df[previous_index]['high']) and                                  float_less(working_df[previous_index]['high'], gap[1])
                elif working_df[previous_index]['tb'] == TopBotType.bot.value:
                    #gap higher than previous low
                    gap_qualify = float_more(gap[1], working_df[previous_index]['high']) and                                  float_more_equal(working_df[previous_index]['high'], working_df[previous_index]['low']) and                                  float_more(working_df[previous_index]['low'], gap[0])
                if gap_qualify:
                    break
        return gap_qualify
        
    def same_tb_remove_previous(self, working_df, previous_index, current_index, next_index):
        working_df[previous_index]['tb'] = TopBotType.noTopBot.value
        previous_index = self.trace_back_index(working_df, previous_index) #current_index # 
        if previous_index is None:
            previous_index = current_index
            current_index = next_index
            next_index = self.get_next_tb(next_index, working_df)
        else:
            if previous_index in self.previous_skipped_idx:
                self.previous_skipped_idx.remove(previous_index)
            
        return previous_index, current_index, next_index

    def same_tb_remove_current(self, working_df, previous_index, current_index, next_index):
        working_df[current_index]['tb'] = TopBotType.noTopBot.value
        temp_index = previous_index
        current_index = previous_index
        previous_index = self.trace_back_index(working_df, previous_index)
        if previous_index is None:
            previous_index = temp_index
            current_index = next_index
            next_index = self.get_next_tb(next_index, working_df)
        else:
            if previous_index in self.previous_skipped_idx:
                self.previous_skipped_idx.remove(previous_index)
        
        return previous_index, current_index, next_index
    
    def same_tb_remove_next(self, working_df, previous_index, current_index, next_index):
        working_df[next_index]['tb'] = TopBotType.noTopBot.value
        temp_index = previous_index
        previous_index = self.trace_back_index(working_df, previous_index)
        if previous_index is None:
            previous_index = temp_index
            next_index = self.get_next_tb(next_index, working_df)
        else:
            next_index = current_index
            current_index = temp_index
            if previous_index in self.previous_skipped_idx:
                self.previous_skipped_idx.remove(previous_index)
            
        return previous_index, current_index, next_index
    

    def defineBi(self):
        '''
        This method defines fenbi for all marked top/bot:
        three indices maintained. 
        if the first two have < 4 new_index distance, we move forward
        if the second two have < 4 new_index distance, we move forward, but mark the first index
        if the second two have >= 4 new_index distance, we make decision on which one to remove, and go backwards
        if we hit all good three kbars, we check marked record and start from there
        finally, if we hit end but still have marked index, we make decision to remove one kbar and resume till finishes
        '''
        
        self.gap_exists() # work out gap in the original kline
        working_df = self.kDataFrame_standardized[self.kDataFrame_standardized['tb']!=TopBotType.noTopBot.value]
        tb = 'tb'
        high = 'high'
        low = 'low'
        new_index = 'new_index'
        
        working_df = self.clean_first_two_tb(working_df)
        
        #################################
        previous_index = 0
        current_index = previous_index + 1
        next_index = current_index + 1
        #################################
        while next_index < working_df.size and previous_index is not None and next_index is not None:
            previousFenXing = working_df[previous_index]
            currentFenXing = working_df[current_index]
            nextFenXing = working_df[next_index]
            
            if currentFenXing[tb] == previousFenXing[tb]: # used to track back the skipped previous_index
                if currentFenXing[tb] == TopBotType.top.value:
                    if float_less(currentFenXing[high], previousFenXing[high]):
                        previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                    elif float_more(currentFenXing[high], previousFenXing[high]):
                        previous_index, current_index, next_index = self.same_tb_remove_previous(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                    else: # equal case
                        gap_qualify = self.check_gap_qualify(working_df, previous_index, current_index, next_index)
                        # only remove current if it's not valid with next in case of equality
                        if working_df[next_index][new_index] - working_df[current_index][new_index] < 4 and not gap_qualify:
                            previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                        else:
                            previous_index, current_index, next_index = self.same_tb_remove_previous(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                    continue
                elif currentFenXing[tb] == TopBotType.bot.value:
                    if float_more(currentFenXing[low], previousFenXing[low]):
                        previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                    elif float_less(currentFenXing[low], previousFenXing[low]):
                        previous_index, current_index, next_index = self.same_tb_remove_previous(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                    else:# equal case
                        gap_qualify = self.check_gap_qualify(working_df, previous_index, current_index, next_index)
                        # only remove current if it's not valid with next in case of equality
                        if working_df[next_index][new_index] - working_df[current_index][new_index] < 4 and not gap_qualify:
                            previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                        else:
                            previous_index, current_index, next_index = self.same_tb_remove_previous(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                    continue
            elif currentFenXing[tb] == nextFenXing[tb]:
                if currentFenXing[tb] == TopBotType.top.value:
                    if float_less(currentFenXing[high], nextFenXing[high]):
                        previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                        
                    elif float_more(currentFenXing[high], nextFenXing[high]):
                        previous_index, current_index, next_index = self.same_tb_remove_next(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                    else: #equality case
                        pre_pre_index = self.trace_back_index(working_df, previous_index)
                        if pre_pre_index is None:
                            previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                            continue
                        gap_qualify = self.check_gap_qualify(working_df, pre_pre_index, previous_index, current_index)
                        if working_df[current_index][new_index] - working_df[previous_index][new_index] >= 4 or gap_qualify:
                            previous_index, current_index, next_index = self.same_tb_remove_next(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                        else:
                            previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                    continue
                elif currentFenXing[tb] == TopBotType.bot.value:
                    if float_more(currentFenXing[low], nextFenXing[low]):
                        previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                    elif float_less(currentFenXing[low], nextFenXing[low]):
                        previous_index, current_index, next_index = self.same_tb_remove_next(working_df, 
                                                                                                 previous_index, 
                                                                                                 current_index, 
                                                                                                 next_index)
                    else:
                        pre_pre_index = self.trace_back_index(working_df, previous_index)
                        if pre_pre_index is None:
                            previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                            continue
                        gap_qualify = self.check_gap_qualify(working_df, pre_pre_index, previous_index, current_index)
                        if working_df[current_index][new_index] - working_df[previous_index][new_index] >= 4 or gap_qualify:
                            previous_index, current_index, next_index = self.same_tb_remove_next(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                        else:
                            previous_index, current_index, next_index = self.same_tb_remove_current(working_df, 
                                                                                                     previous_index, 
                                                                                                     current_index, 
                                                                                                     next_index)
                    continue
            
            gap_qualify = self.check_gap_qualify(working_df, previous_index, current_index, next_index)
            if currentFenXing[new_index] - previousFenXing[new_index] < 4:
                # comming from current next less than 4 new_index gap, we need to determine which ones to kill
                # once done we trace back
                if (nextFenXing[new_index] - currentFenXing[new_index]) >= 4 or gap_qualify:
                    pre_pre_index = self.trace_back_index(working_df, previous_index)
                    
                    # if previous current are good, we go next
                    if self.check_gap_qualify(working_df, pre_pre_index, previous_index, current_index):
                        pass
                    
                    elif currentFenXing[tb] == TopBotType.bot.value and                        previousFenXing[tb] == TopBotType.top.value and                        nextFenXing[tb] == TopBotType.top.value:
                        if float_more_equal(previousFenXing[high], nextFenXing[high]):
                            # still can't make decision, but we can have idea about prepre case
                            pre_pre_index = self.trace_back_index(working_df, previous_index)
                            if pre_pre_index is None:
                                working_df[current_index][tb] = TopBotType.noTopBot.value
                                current_index = next_index
                                next_index = self.get_next_tb(next_index, working_df)
                                continue
                            
                            if pre_pre_index in self.previous_skipped_idx:
                                self.previous_skipped_idx.remove(pre_pre_index)
                            prepreFenXing = working_df[pre_pre_index]
                            if float_more_equal(prepreFenXing[low], currentFenXing[low]):
                                working_df[pre_pre_index][tb] = TopBotType.noTopBot.value
                                temp_index = self.trace_back_index(working_df, pre_pre_index)
                                if temp_index is None:
                                    working_df[current_index][tb] = TopBotType.noTopBot.value
                                    current_index = next_index
                                    next_index = self.get_next_tb(next_index, working_df)
                                else:
                                    next_index = current_index
                                    current_index = previous_index
                                    previous_index = temp_index
                                    if previous_index in self.previous_skipped_idx:
                                        self.previous_skipped_idx.remove(previous_index)
                                continue
                            else:
                                working_df[current_index][tb] = TopBotType.noTopBot.value
                                current_index = previous_index
                                previous_index = self.trace_back_index(working_df, previous_index)
                                if previous_index in self.previous_skipped_idx:
                                    self.previous_skipped_idx.remove(previous_index)
                                continue
                        else: #previousFenXing[high] < nextFenXing[high]
                            working_df[previous_index][tb] = TopBotType.noTopBot.value
                            previous_index = self.trace_back_index(working_df, previous_index)
                            if previous_index in self.previous_skipped_idx:
                                self.previous_skipped_idx.remove(previous_index)
                            continue
                            
                    elif currentFenXing[tb] == TopBotType.top.value and                        previousFenXing[tb] == TopBotType.bot.value and                        nextFenXing[tb] == TopBotType.bot.value:
                        if float_less(previousFenXing[low], nextFenXing[low]):
                            # still can't make decision, but we can have idea about prepre case
                            pre_pre_index = self.trace_back_index(working_df, previous_index)
                            if pre_pre_index is None:
                                working_df[current_index][tb] = TopBotType.noTopBot.value
                                current_index = next_index
                                next_index = self.get_next_tb(next_index, working_df)
                                continue
                            
                            if pre_pre_index in self.previous_skipped_idx:
                                self.previous_skipped_idx.remove(pre_pre_index)
                            prepreFenXing = working_df[pre_pre_index]
                            if float_less_equal(prepreFenXing[high], currentFenXing[high]):
                                working_df[pre_pre_index][tb] = TopBotType.noTopBot.value
                                temp_index = self.trace_back_index(working_df, pre_pre_index)
                                if temp_index is None:
                                    working_df[current_index][tb] = TopBotType.noTopBot.value
                                    current_index = next_index
                                    next_index = self.get_next_tb(next_index, working_df)
                                else:
                                    next_index = current_index
                                    current_index = previous_index
                                    previous_index = temp_index
                                    if previous_index in self.previous_skipped_idx:
                                        self.previous_skipped_idx.remove(previous_index)
                                continue
                            else:
                                working_df[current_index][tb] = TopBotType.noTopBot.value
                                current_index = previous_index
                                previous_index = self.trace_back_index(working_df, previous_index)
                                if previous_index in self.previous_skipped_idx:
                                    self.previous_skipped_idx.remove(previous_index)
                                continue
                        else: #previousFenXing[low] >= nextFenXing[low]
                            working_df[previous_index][tb] = TopBotType.noTopBot.value
                            previous_index = self.trace_back_index(working_df, previous_index)
                            if previous_index in self.previous_skipped_idx:
                                self.previous_skipped_idx.remove(previous_index)
                            continue
                else: #(nextFenXing[new_index] - currentFenXing[new_index]) < 4 and not gap_qualify:
                    temp_index = self.get_next_tb(next_index, working_df)
                    if temp_index == working_df.size: # we reached the end, need to go back
                        previous_index, current_index, next_index = self.work_on_end(previous_index, 
                                                                                     current_index, 
                                                                                     next_index, 
                                                                                     working_df)
                    else:
                        # leave it for next round again!
                        self.previous_skipped_idx.append(previous_index) # mark index so we come back 
                        previous_index = current_index
                        current_index = next_index
                        next_index = temp_index
                    continue
                
            elif (nextFenXing[new_index] - currentFenXing[new_index]) < 4 and not gap_qualify: 
                temp_index = self.get_next_tb(next_index, working_df)
                if temp_index == working_df.size: # we reached the end, need to go back
                    previous_index, current_index, next_index = self.work_on_end(previous_index, 
                                                                                 current_index, 
                                                                                 next_index, 
                                                                                 working_df)
                else:
                    # leave it for next round again!
                    self.previous_skipped_idx.append(previous_index) # mark index so we come back 
                    previous_index = current_index
                    current_index = next_index
                    next_index = temp_index
                continue
            elif (nextFenXing[new_index] - currentFenXing[new_index]) >= 4 or gap_qualify:
                if currentFenXing[tb] == TopBotType.top.value and nextFenXing[tb] == TopBotType.bot.value and float_more(currentFenXing[high], nextFenXing[high]):
                    pass
                elif currentFenXing[tb] == TopBotType.top.value and nextFenXing[tb] == TopBotType.bot.value and float_less_equal(currentFenXing[high], nextFenXing[high]):
                    working_df[current_index][tb] = TopBotType.noTopBot.value
                    current_index = next_index
                    next_index = self.get_next_tb(next_index, working_df)
                    continue
                
                elif currentFenXing[tb] == TopBotType.top.value and nextFenXing[tb] == TopBotType.bot.value and float_less_equal(currentFenXing[low],nextFenXing[low]):
                    working_df[next_index][tb] = TopBotType.noTopBot.value
                    next_index = self.get_next_tb(next_index, working_df)
                    continue
                elif currentFenXing[tb] == TopBotType.top.value and nextFenXing[tb] == TopBotType.bot.value and float_more(currentFenXing[low], nextFenXing[low]):
                    pass
                
                elif currentFenXing[tb] == TopBotType.bot.value and nextFenXing[tb] == TopBotType.top.value and float_less(currentFenXing[low], nextFenXing[low]):
                    pass
                elif currentFenXing[tb] == TopBotType.bot.value and nextFenXing[tb] == TopBotType.top.value and float_more_equal(currentFenXing[low], nextFenXing[low]):
                    working_df[current_index][tb] = TopBotType.noTopBot.value
                    current_index = next_index 
                    next_index = self.get_next_tb(next_index, working_df)
                    continue
                elif currentFenXing[tb] == TopBotType.bot.value and nextFenXing[tb] == TopBotType.top.value and float_less(currentFenXing[high], nextFenXing[high]):
                    pass
                elif currentFenXing[tb] == TopBotType.bot.value and nextFenXing[tb] == TopBotType.top.value and float_more_equal(currentFenXing[high], nextFenXing[high]):
                    working_df[next_index][tb] = TopBotType.noTopBot.value
                    next_index = self.get_next_tb(next_index, working_df)
                    continue
            
            if self.previous_skipped_idx: # if we still have some left to do
                previous_index = self.previous_skipped_idx.pop()
                if working_df[previous_index][tb] == TopBotType.noTopBot.value:
                    previous_index = self.get_next_tb(previous_index, working_df)
                current_index = self.get_next_tb(previous_index, working_df)
                next_index = self.get_next_tb(current_index, working_df)
                continue
            
            # only confirmed tb comes here
            previous_index = current_index
            current_index=next_index
            next_index = self.get_next_tb(next_index, working_df)

        # if nextIndex is the last one, final clean up
        if next_index == working_df.size:
            if ((working_df[current_index][tb]==TopBotType.top.value and float_more(self.kDataFrame_origin[-1][high], working_df[current_index][high]))                 or (working_df[current_index][tb]==TopBotType.bot.value and float_less(self.kDataFrame_origin[-1][low], working_df[current_index][low]) )):
                working_df[-1][tb] = working_df[current_index][tb]
                working_df[current_index][tb] = TopBotType.noTopBot.value
            
            if working_df[current_index][tb] == TopBotType.noTopBot.value and                ((working_df[previous_index][tb]==TopBotType.top.value and float_more(self.kDataFrame_origin[-1][high], working_df[previous_index][high])) or                 (working_df[previous_index][tb]==TopBotType.bot.value and float_less(self.kDataFrame_origin[-1][low], working_df[previous_index][low]))):
                working_df[-1][tb] = working_df[previous_index][tb]
                working_df[previous_index][tb] = TopBotType.noTopBot.value
                
            if working_df[previous_index][tb] == working_df[current_index][tb]:
                if working_df[current_index][tb] == TopBotType.top.value:
                    if float_more(working_df[current_index][high],working_df[previous_index][high]):
                        working_df[previous_index][tb] = TopBotType.noTopBot.value
                    else:
                        working_df[current_index][tb] = TopBotType.noTopBot.value
                elif working_df[current_index][tb] == TopBotType.bot.value:
                    if float_less(working_df[current_index][low], working_df[previous_index][low]):
                        working_df[previous_index][tb] = TopBotType.noTopBot.value
                    else:
                        working_df[current_index][tb] = TopBotType.noTopBot.value
        ###################################    
        self.kDataFrame_marked = working_df[working_df[tb]!=TopBotType.noTopBot.value][FEN_BI_COLUMNS]
        if self.isdebug:
            print("self.kDataFrame_marked head 20:{0}".format(self.kDataFrame_marked[:20]))
            print("self.kDataFrame_marked tail 20:{0}".format(self.kDataFrame_marked[-20:]))


    def work_on_end(self, pre_idx, cur_idx, nex_idx, working_df):
        '''
        only triggered at the end of fenbi loop
        '''
        previousFenXing = working_df[pre_idx]
        currentFenXing = working_df[cur_idx]
        nextFenXing = working_df[nex_idx]

        if currentFenXing['tb'] == TopBotType.top.value:
            if float_more(previousFenXing['low'], nextFenXing['low']):
                working_df[pre_idx]['tb'] = TopBotType.noTopBot.value
                pre_idx = self.trace_back_index(working_df, pre_idx)
            else:
                working_df[nex_idx]['tb'] = TopBotType.noTopBot.value
                nex_idx = cur_idx
                cur_idx = pre_idx
                pre_idx = self.trace_back_index(working_df, pre_idx)
        else: # TopBotType.bot
            if float_less(previousFenXing['high'], nextFenXing['high']):
                working_df[pre_idx]['tb'] = TopBotType.noTopBot.value
                pre_idx = self.trace_back_index(working_df, pre_idx)
            else:
                working_df[nex_idx]['tb'] = TopBotType.noTopBot.value
                nex_idx = cur_idx
                cur_idx = pre_idx
                pre_idx = self.trace_back_index(working_df, pre_idx)
        if pre_idx in self.previous_skipped_idx:
            self.previous_skipped_idx.remove(pre_idx)
        return pre_idx, cur_idx, nex_idx

    def getMarkedBL(self):
        self.standardize()
        self.markTopBot()
        self.defineBi()
#         self.defineBi_new()
        self.getPureBi()
        return self.kDataFrame_marked
    
    def getPureBi(self):
        # only use the price relavent
        self.kDataFrame_marked = append_fields(self.kDataFrame_marked,
                                               'chan_price',
                                               [0]*len(self.kDataFrame_marked),
                                               float,
                                               usemask=False)
        i = 0
        while i < self.kDataFrame_marked.size:
            item = self.kDataFrame_marked[i]
            if item['tb'] == TopBotType.top.value:
                self.kDataFrame_marked[i]['chan_price'] = item['high']
            elif item['tb'] == TopBotType.bot.value:
                self.kDataFrame_marked[i]['chan_price'] = item['low']
            else:
                print("Invalid tb for chan_price")
            i = i + 1
            
        if self.isdebug:
            print("getPureBi:{0}".format(self.kDataFrame_marked[['date', 'chan_price', 'tb', 'real_loc']][-20:]))

    def getFenBi(self, initial_state=TopBotType.noTopBot):
        self.standardize(initial_state)
        self.markTopBot(initial_state)
        self.defineBi()
        self.getPureBi()
        return self.kDataFrame_marked

    def getFenDuan(self, initial_state=TopBotType.noTopBot):
        temp_df = self.getFenBi(initial_state)
        if temp_df.size==0:
            return temp_df
        self.defineXD(initial_state)
        return self.kDataFrame_xd
    
    def getOriginal_df(self):
        return self.kDataFrame_origin
    
    def getFenBI_df(self):
        return self.kDataFrame_marked
    
    def getFenDuan_df(self):
        return self.kDataFrame_xd


################################################## XD defintion ##################################################      

    def find_initial_direction(self, working_df, initial_status=TopBotType.noTopBot):
        chan_price = 'chan_price'
        if initial_status != TopBotType.noTopBot:
            # first six elem, this can only be used when we are sure about the direction of the xd
            if initial_status == TopBotType.top:
                initial_loc = working_df[:6]['chan_price'].argmax(axis=0)
            elif initial_status == TopBotType.bot:
                initial_loc = working_df[:6]['chan_price'].argmin(axis=0)
            else:
                initial_loc = None
                print("Invalid Initial TopBot type")
            working_df[initial_loc]['xd_tb'] = initial_status.value
            if self.isdebug:
                print("initial xd_tb:{0} located at {1}".format(initial_status, working_df[initial_loc]['date']))
            initial_direction = TopBotType.top2bot if initial_status == TopBotType.top else TopBotType.bot2top
        else:
            initial_loc = current_loc = 0
            initial_direction = TopBotType.noTopBot
            while current_loc + 3 < working_df.size:
                first = working_df[current_loc]
                second = working_df[current_loc+1]
                third = working_df[current_loc+2]
                forth = working_df[current_loc+3]
                
                if float_less(first[chan_price], second[chan_price]):
                    found_direction = (float_less_equal(first[chan_price],third[chan_price]) and float_less(second[chan_price],forth[chan_price])) or                                        (float_more_equal(first[chan_price],third[chan_price]) and float_more(second[chan_price],forth[chan_price]))
                else:
                    found_direction = (float_less(first[chan_price],third[chan_price]) and float_less_equal(second[chan_price],forth[chan_price])) or                                        (float_more(first[chan_price],third[chan_price]) and float_more_equal(second[chan_price],forth[chan_price]))
                                    
                if found_direction:
                    initial_direction = TopBotType.bot2top if (float_less(first[chan_price],third[chan_price]) or float_less(second[chan_price],forth[chan_price])) else TopBotType.top2bot
                    initial_loc = current_loc
                    break
                else:
                    current_loc = current_loc + 1
            
        return initial_loc, initial_direction

    def combine_gaps(self, gap_regions):
        '''
        gap regions come in as ordered
        '''
        i = 0 
        if len(gap_regions) <= 1:
            return gap_regions
        
        # sort gap regions
        gap_regions = sorted(gap_regions, key=lambda tup: tup[0])
        
        new_gaps = []
        temp_range= None
        while i + 1 < len(gap_regions):
            current_range = gap_regions[i]
            next_range = gap_regions[i+1]
            
            if temp_range is None:
                if float_more_equal(current_range[1], next_range[0]):
                    temp_range = (current_range[0], next_range[1])
                else:
                    new_gaps.append(current_range)
                    temp_range = next_range
            else:
                if float_more_equal(temp_range[1], next_range[0]):
                    temp_range = (temp_range[0], next_range[1])
                else:
                    new_gaps.append(temp_range)
                    temp_range = next_range
            i = i + 1
        new_gaps.append(temp_range)
                
        return new_gaps

    def kbar_gap_as_xd(self, working_df, first_idx, second_idx, compare_idx):
        '''
        check given gapped kbar can be considered xd alone
        '''
        firstElem = working_df[first_idx]
        secondElem = working_df[second_idx]
        compareElem = working_df[compare_idx] if compare_idx is not None else None
        item_price_covered = False
        gap_range_in_portion = False
        if first_idx + 1 == second_idx and            self.gap_exists_in_range(firstElem['date'], secondElem['date']):
            gap_direction = TopBotType.bot2top if secondElem['tb'] == TopBotType.top.value else                            TopBotType.top2bot if secondElem['tb'] == TopBotType.bot.value else                            TopBotType.noTopBot
            regions = self.gap_region(firstElem['date'], secondElem['date'], gap_direction)
            if regions:
                regions = self.combine_gaps(regions)
    #             for re in regions:
    # #                 if float_less_equal(re[0], compareElem['chan_price']) and float_less_equal(compareElem['chan_price'], re[1]):
    # #                     item_price_covered = True
    #                 if float_more_equal((re[1]-re[0])/abs(firstElem['chan_price']-secondElem['chan_price']), GOLDEN_RATIO):
    #                     gap_range_in_portion = True
    #                 if gap_range_in_portion:
    #                     return gap_range_in_portion
                    
                gap_range = sum([(b-a) for a, b in regions])
                if float_more_equal(gap_range/abs(firstElem['chan_price']-secondElem['chan_price']), 1-GOLDEN_RATIO):
                    gap_range_in_portion = True
                
                if compareElem is None:
                    item_price_covered = True
                else:
                    if gap_direction == TopBotType.top2bot:
                        item_price_covered = float_less_equal(regions[0][0], compareElem['chan_price'])
                    elif gap_direction == TopBotType.bot2top:
                        item_price_covered = float_more_equal(regions[-1][1], compareElem['chan_price'])
                    else:
                        item_price_covered = False
                
                if gap_range_in_portion and item_price_covered:
                    return True
        return False
    

    def xd_inclusion(self, firstElem, secondElem, thirdElem, forthElem):
        '''
        given four elem check the xd formed contain inclusive relationship, positive as True, negative as False
        '''
        if (float_less_equal(firstElem['chan_price'], thirdElem['chan_price']) and float_more_equal(secondElem['chan_price'], forthElem['chan_price'])) or            (float_more_equal(firstElem['chan_price'], thirdElem['chan_price']) and float_less_equal(secondElem['chan_price'], forthElem['chan_price'])):
            return True
        return False

    def is_XD_inclusion_free(self, direction, next_valid_elems, working_df):
        '''
        check the 4 elems are inclusion free by direction, if not operate the inclusion, gaps are defined as pure gap
        return two values:
        if inclusion free 
        if kbar gap as xd
        '''
        if len(next_valid_elems) < 4:
            if self.isdebug:
                print("Invalid number of elems found")
            return False, False
        
        firstElem = working_df[next_valid_elems[0]]
        secondElem = working_df[next_valid_elems[1]]
        thirdElem = working_df[next_valid_elems[2]]
        forthElem = working_df[next_valid_elems[3]]
        tb = 'tb'
        chan_price = 'chan_price'
        if direction == TopBotType.top2bot:
            assert firstElem[tb] == thirdElem[tb] == TopBotType.bot.value and secondElem[tb] == forthElem[tb] == TopBotType.top.value, "Invalid starting tb status for checking inclusion top2bot: {0}, {1}, {2}, {3}".format(firstElem, thirdElem, secondElem, forthElem)
        elif direction == TopBotType.bot2top:
            assert firstElem[tb] == thirdElem[tb] == TopBotType.top.value and  secondElem[tb] == forthElem[tb] == TopBotType.bot.value, "Invalid starting tb status for checking inclusion bot2top: {0}, {1}, {2}, {3}".format(firstElem, thirdElem, secondElem, forthElem)       
        
        if self.xd_inclusion(firstElem, secondElem, thirdElem, forthElem):  
            ############################## special case of kline gap as XD ##############################
            # only checking if any one node is in pure gap range. The same logic as gap for XD
            if self.kbar_gap_as_xd(working_df, next_valid_elems[0], next_valid_elems[1], None) or                self.kbar_gap_as_xd(working_df, next_valid_elems[2], next_valid_elems[3], None) or                self.kbar_gap_as_xd(working_df, next_valid_elems[1], next_valid_elems[2], None):
                if self.isdebug:
                    print("inclusion ignored due to kline gaps, with loc {0}@{1}, {2}@{3}, {4}@{5}, {6}@{7}".format(firstElem['date'], 
                                                                                                                  firstElem['chan_price'],
                                                                                                                  secondElem['date'],
                                                                                                                  secondElem['chan_price'],
                                                                                                                  thirdElem['date'], 
                                                                                                                  thirdElem['chan_price'],
                                                                                                                  forthElem['date'],
                                                                                                                  forthElem['chan_price'],
                                                                                                                  ))
                return True, True
            ############################## special case of kline gap as XD ##############################                
            
            # We need to be careful of which nodes to remove!
            removed_loc_1 = removed_loc_2 = 0
            if direction == TopBotType.top2bot:
                if float_less(firstElem[chan_price], thirdElem[chan_price]):
                    working_df[next_valid_elems[1]][tb] = TopBotType.noTopBot.value
                    working_df[next_valid_elems[2]][tb] = TopBotType.noTopBot.value
                    removed_loc_1 = 1
                    removed_loc_2 = 2
                else:
                    working_df[next_valid_elems[0]][tb] = TopBotType.noTopBot.value
                    working_df[next_valid_elems[1]][tb] = TopBotType.noTopBot.value
                    removed_loc_1 = 0
                    removed_loc_2 = 1
            else: # bot2top
                if float_more(firstElem[chan_price], thirdElem[chan_price]):
                    working_df[next_valid_elems[1]][tb] = TopBotType.noTopBot.value
                    working_df[next_valid_elems[2]][tb] = TopBotType.noTopBot.value
                    removed_loc_1 = 1
                    removed_loc_2 = 2
                else:
                    working_df[next_valid_elems[0]][tb] = TopBotType.noTopBot.value
                    working_df[next_valid_elems[1]][tb] = TopBotType.noTopBot.value
                    removed_loc_1 = 0
                    removed_loc_2 = 1

            
            if self.isdebug:
                print("location {0}@{1}, {2}@{3} removed for combination".format(working_df[next_valid_elems[removed_loc_1]]['date'], 
                                                                                 working_df[next_valid_elems[removed_loc_1]][chan_price], 
                                                                                 working_df[next_valid_elems[removed_loc_2]]['date'], 
                                                                                 working_df[next_valid_elems[removed_loc_2]][chan_price]))
            return False, False
        
        return True, False
    

    def check_inclusion_by_direction(self, current_loc, working_df, direction, count_num=6):
        '''
        count_num can be 4, 6, 8 to suit different needs
        '''
        i = current_loc
        first_run = True

#         count_num = 8 if with_gap else 6
        # for without gap case we need to make sure all second and third (carry forward as well) 
        # elem are inclusion free that results 6 nodes to be tested
        # for with gap case we need to test all first second and third elem (not carry forward) 
        # this also results 6 nodes to be tested
            
        while first_run or (i+count_num-1 < working_df.shape[0]):
            first_run = False
            
            next_valid_elems = self.get_next_N_elem(i, working_df, count_num)
            
            if len(next_valid_elems) < count_num:
                break
            
            # we need to either get to last layer of is_inclusion_free or any level of is_kline_gap_xd
            if count_num == 4:
                is_inclusion_free, _ = self.is_XD_inclusion_free(direction, next_valid_elems[:4], working_df)
                if is_inclusion_free:
                    break
            elif count_num == 6:
                is_inclusion_free, is_kline_gap_xd = self.is_XD_inclusion_free(direction, next_valid_elems[:4], working_df)
                if is_kline_gap_xd:
                    break
                if is_inclusion_free:
                    is_inclusion_free, _ = self.is_XD_inclusion_free(direction, next_valid_elems[-4:], working_df)
                    if is_inclusion_free:
                        break
            else: #count_num == 8:
                is_inclusion_free, is_kline_gap_xd = self.is_XD_inclusion_free(direction, next_valid_elems[:4], working_df)
                if is_kline_gap_xd:
                    break
                if is_inclusion_free:
                    is_inclusion_free, is_kline_gap_xd = self.is_XD_inclusion_free(direction, next_valid_elems[2:6], working_df)
                    if is_kline_gap_xd:
                        break
                    if is_inclusion_free:
                        is_inclusion_free, _ = self.is_XD_inclusion_free(direction, next_valid_elems[-4:], working_df)
                        if is_inclusion_free:
                            break
        return next_valid_elems
                

    def check_current_gap(self, first, second, third, forth):
        '''
        giving the first four elem, find out if current gap exists
        '''
        tb = 'tb'
        chan_price = 'chan_price'
        with_gap = False
        if third[tb] == TopBotType.top.value:
            with_gap = float_less(first[chan_price], forth[chan_price])
        elif third[tb] == TopBotType.bot.value:
            with_gap = float_more(first[chan_price], forth[chan_price])
        else:
            print("Error, invalid tb status!")
        return with_gap

    def check_XD_topbot(self, first, second, third, forth, fifth, sixth):
        '''
        check if current 5 BI (6 bi tb) form XD top or bot
        check if gap between first and third BI
        '''
        tb = 'tb'
        chan_price = 'chan_price'
        assert first[tb] == third[tb] == fifth[tb] and second[tb] == forth[tb] == sixth[tb], "invalid tb status!"
        
        result_status = TopBotType.noTopBot
        with_gap = False
        
        if third[tb] == TopBotType.top.value:
            with_gap = float_less(first[chan_price], forth[chan_price])
            if float_more(third[chan_price], first[chan_price]) and             float_more(third[chan_price], fifth[chan_price]) and             float_more(forth[chan_price], sixth[chan_price]):
                result_status = TopBotType.top
                
        elif third[tb] == TopBotType.bot.value:
            with_gap = float_more(first[chan_price], forth[chan_price])
            if float_less(third[chan_price], first[chan_price]) and             float_less(third[chan_price], fifth[chan_price]) and             float_less(forth[chan_price], sixth[chan_price]):
                result_status = TopBotType.bot
                            
        else:
            print("Error, invalid tb status!")
        
        return result_status, with_gap
    

    def check_kline_gap_as_xd(self, next_valid_elems, working_df, direction):
        first = working_df[next_valid_elems[0]]
        second = working_df[next_valid_elems[1]]
        third = working_df[next_valid_elems[2]]
        forth = working_df[next_valid_elems[3]]
        fifth = working_df[next_valid_elems[4]]
        xd_gap_result = TopBotType.noTopBot
        without_gap = False
        with_kline_gap_as_xd = False

        # check the corner case where xd can be formed by a single kline gap
        # if kline gap (from original data) exists between second and third or third and forth
        # A if so only check if third is top or bot comparing with first, 
        # B with_gap is determined by checking if the kline gap range cover between first and forth
        # C change direction as usual, and increment counter by 1 only
        chan_price = 'chan_price'
        if not self.previous_with_xd_gap and            self.kbar_gap_as_xd(working_df, next_valid_elems[2], next_valid_elems[3], next_valid_elems[1]):
            without_gap = with_kline_gap_as_xd = True
            self.previous_with_xd_gap = True
            if self.isdebug:
                print("XD represented by kline gap 2, {0}, {1}".format(working_df[next_valid_elems[2]]['date'], working_df[next_valid_elems[3]]['date']))
        
        if not with_kline_gap_as_xd and self.previous_with_xd_gap:
            self.previous_with_xd_gap=False # close status
            if self.kbar_gap_as_xd(working_df, next_valid_elems[1], next_valid_elems[2], next_valid_elems[0]):
                without_gap = with_kline_gap_as_xd = True
                if self.isdebug:
                    print("XD represented by kline gap 1, {0}, {1}".format(working_df[next_valid_elems[1]]['date'], working_df[next_valid_elems[2]]['date']))

        if with_kline_gap_as_xd: # we don't need to compare with the first elem
            if (direction == TopBotType.bot2top and float_more(third[chan_price], fifth[chan_price])): #and float_more(third[chan_price], first[chan_price])
                xd_gap_result = TopBotType.top
            elif (direction == TopBotType.top2bot and float_less(third[chan_price], fifth[chan_price])): #and float_less(third[chan_price], first[chan_price]) 
                xd_gap_result = TopBotType.bot
            else:
                if self.isdebug:
                    print("XD represented by kline gap 3")
        
        return xd_gap_result, not without_gap, with_kline_gap_as_xd
    
    
    def check_previous_elem_to_avoid_xd_gap(self, with_gap, next_valid_elems, working_df):
        tb = 'tb'
        chan_price = 'chan_price'
        first = working_df[next_valid_elems[0]]
        forth = working_df[next_valid_elems[3]]
        previous_elem = self.get_previous_N_elem(next_valid_elems[0], 
                                                 working_df, 
                                                 N=0, 
                                                 end_tb=TopBotType.value2type(first[tb]), 
                                                 single_direction=True)
        if len(previous_elem) >= 1: # use single direction at least 1 needed
            if first[tb] == TopBotType.top.value:
                with_gap = float_less(working_df[previous_elem][chan_price].max(), forth[chan_price])
            elif first[tb] == TopBotType.bot.value:
                with_gap = float_more(working_df[previous_elem][chan_price].min(), forth[chan_price])
            else:
                assert first[tb] == TopBotType.top.value or first[tb] == TopBotType.bot.value, "Invalid first elem tb"
        if not with_gap and self.isdebug:
            print("elem gap unchecked at {0}".format(working_df[next_valid_elems[0]]['date']))
        return with_gap  
    
    def check_XD_topbot_directed(self, next_valid_elems, direction, working_df):
        first = working_df[next_valid_elems[0]]
        second = working_df[next_valid_elems[1]]
        third = working_df[next_valid_elems[2]]
        forth = working_df[next_valid_elems[3]]
        fifth = working_df[next_valid_elems[4]]
        sixth = working_df[next_valid_elems[5]]     
        with_kline_gap_as_xd = False
        
        xd_gap_result, with_current_gap, with_kline_gap_as_xd = self.check_kline_gap_as_xd(next_valid_elems, working_df, direction)
        
        if with_kline_gap_as_xd and xd_gap_result != TopBotType.noTopBot:
            return xd_gap_result, with_current_gap, with_kline_gap_as_xd
        
        result, with_current_gap = self.check_XD_topbot(first, second, third, forth, fifth, sixth)
        
        if (result == TopBotType.top and direction == TopBotType.bot2top) or (result == TopBotType.bot and direction == TopBotType.top2bot):
            if with_current_gap: # check previous elements to see if the gap can be closed TESTED!
                with_current_gap = self.check_previous_elem_to_avoid_xd_gap(with_current_gap, next_valid_elems, working_df)
            return result, with_current_gap, with_kline_gap_as_xd
        else:
            return TopBotType.noTopBot, with_current_gap, with_kline_gap_as_xd
        
    def defineXD(self, initial_status=TopBotType.noTopBot):
        working_df = self.kDataFrame_marked[['date', 'close', 'high', 'low', 'chan_price', 'tb','real_loc']] # real_loc used for central region
        
        working_df = append_fields(working_df,
                                   ['original_tb', 'xd_tb'],
                                   [working_df['tb'], [TopBotType.noTopBot.value] * working_df.size],
                                   usemask=False)

        if working_df.size==0:
            self.kDataFrame_xd = working_df
            return working_df
    
        # find initial direction
        initial_i, initial_direction = self.find_initial_direction(working_df, initial_status)
        
        # loop through to find XD top bot
        working_df = self.find_XD(initial_i, initial_direction, working_df)
        
        working_df = working_df[(working_df['xd_tb']==TopBotType.top.value) | (working_df['xd_tb']==TopBotType.bot.value)]
            
        self.kDataFrame_xd = working_df[FEN_DUAN_COLUMNS]
        if self.isdebug:
            print("self.kDataFrame_xd:{0}".format(self.kDataFrame_xd))
        return working_df
    
    def get_next_N_elem(self, loc, working_df, N=4, start_tb=TopBotType.noTopBot, single_direction=False):
        '''
        get the next N number of elems if tb isn't noTopBot, 
        if start_tb is set, find the first N number of elems starting with tb given
        starting from loc(inclusive)
        '''
        i = loc
        result_locs = []
        while i < working_df.size:
            current_elem = working_df[i]
            if current_elem['tb'] != TopBotType.noTopBot.value:
                if start_tb != TopBotType.noTopBot and current_elem['tb'] != start_tb.value and len(result_locs) == 0:
                    i = i + 1
                    continue
                if single_direction and current_elem['tb'] != start_tb.value:
                    i = i + 1
                    continue
                result_locs.append(i)
                if len(result_locs) == N:
                    break
            i = i + 1
        return result_locs
    
    
    def get_previous_N_elem(self, loc, working_df, N=0, end_tb=TopBotType.noTopBot, single_direction=True):
        '''
        get the previous N number of elems if tb isn't noTopBot, 
        if start_tb is set, find the first N number of elems ending with tb given (order preserved)
        ending with loc (exclusive)
        We are only expecting elem from the same XD, meaning the same direction. So we fetch upto previous xd_tb if N == 0
        single_direction meaning only return elem with the same tb as end_tb
        We are checking the original_tb field to avoid BI been combined. 
        This function is only used for xd gap check
        '''
        i = loc-1
        result_locs = []
        while i >= 0:
            current_elem = working_df[i]
            if current_elem['original_tb'] != TopBotType.noTopBot.value:
                if end_tb != TopBotType.noTopBot and current_elem['original_tb'] != end_tb.value and len(result_locs) == 0:
                    i = i - 1
                    continue
                if single_direction: 
                    if current_elem['original_tb'] == end_tb.value:
                        result_locs.insert(0, i)
                else:
                    result_locs.insert(0, i)
                if N != 0 and len(result_locs) == N:
                    break
                if N == 0 and (current_elem['xd_tb'] == TopBotType.top.value or current_elem['xd_tb'] == TopBotType.bot.value):
                    break
            i = i - 1
        return result_locs
    
    def xd_topbot_candidate(self, next_valid_elems, current_direction, working_df, with_current_gap):
        '''
        check current candidates BIs are positioned as idx is at tb
        we are only expecting newly found index to move forward
        
        added extra check after inclusion done
        '''
        result = None
        
        # simple check
        if len(next_valid_elems) != 3 and self.isdebug:
            print("Invalid number of tb elem passed in")
        
        chan_price_list = [working_df[nv]['chan_price'] for nv in next_valid_elems]
            
        if current_direction == TopBotType.top2bot:
            min_value = min(chan_price_list) 
            min_index = chan_price_list.index(min_value)  
            if min_index > 1: # ==2
                result = next_valid_elems[min_index-1] # navigate to the starting for current bot
             
        elif current_direction == TopBotType.bot2top:
            max_value = max(chan_price_list) 
            max_index = chan_price_list.index(max_value)
            if max_index > 1:
                result = next_valid_elems[max_index-1] # navigate to the starting for current bot
        
        if result is not None:
            return result
        
        # check with inclusion
        if with_current_gap:
            new_valid_elems = self.check_inclusion_by_direction(next_valid_elems[1], working_df, current_direction, count_num=4)
        else:
            new_valid_elems = self.check_inclusion_by_direction(next_valid_elems[1], working_df, current_direction, count_num=6)
        
        # we only care about the next 4 elements there goes 0 -> 3
        end_loc = new_valid_elems[3]+1 if len(new_valid_elems) >= 4 else None
        affected_chan_prices = working_df[new_valid_elems[0]:end_loc]['chan_price']
        
        if current_direction == TopBotType.top2bot:
            min_price = min(affected_chan_prices)
            if float_less(min_price, working_df[next_valid_elems[1]]['chan_price']):
                result = next_valid_elems[1] # next candidate
        else:
            max_price = max(affected_chan_prices)
            if float_more(max_price, working_df[next_valid_elems[1]]['chan_price']):
                result = next_valid_elems[1]
        
        if result is not None: # restore data
#             working_df[next_valid_elems[1]:new_valid_elems[-1]]['tb'] = working_df[next_valid_elems[1]:new_valid_elems[-1]]['original_tb']
#             if self.isdebug:
#                 print("tb data restored from {0} to {1} real_loc {2} to {3}".format(working_df[next_valid_elems[1]]['date'], 
#                                                                                     working_df[new_valid_elems[-1]]['date'], 
#                                                                                     working_df[next_valid_elems[1]]['real_loc'], 
#                                                                                     working_df[new_valid_elems[-1]]['real_loc']))
            self.restore_tb_data(working_df, next_valid_elems[1], new_valid_elems[-1])
        return result
    
    def restore_tb_data(self, working_df, from_idx, to_idx):
        working_df[from_idx:to_idx]['tb'] = working_df[from_idx:to_idx]['original_tb']
        if self.isdebug:
            print("tb data restored from {0} to {1} real_loc {2} to {3}".format(working_df[from_idx]['date'], 
                                                                                working_df[to_idx if to_idx is not None else -1]['date'], 
                                                                                working_df[from_idx]['real_loc'], 
                                                                                working_df[to_idx if to_idx is not None else -1]['real_loc']))
 
    
    def pop_gap(self, working_df, next_valid_elems, current_direction):
        chan_price = 'chan_price'
        tb = 'tb'
        original_tb = 'original_tb'
        xd_tb='xd_tb'
        date='date'
        real_loc='real_loc'
        i = None
        #################### pop gap_XD ##########################
        checking_elems_price = working_df[next_valid_elems[0]:next_valid_elems[-1]+1][chan_price]
        
        previous_gap_elem = working_df[self.gap_XD[-1]]
        if current_direction == TopBotType.top2bot:
            if float_more(max(checking_elems_price), previous_gap_elem[chan_price]):
                previous_gap_loc = self.gap_XD.pop()
                if self.isdebug:
                    print("xd_tb cancelled due to new high found: {0} {1}".format(working_df[previous_gap_loc][date], working_df[previous_gap_loc][real_loc]))
                working_df[previous_gap_loc][xd_tb] = TopBotType.noTopBot.value
                
                self.restore_tb_data(working_df, previous_gap_loc, next_valid_elems[-1])
                current_direction = TopBotType.reverse(current_direction)
                if self.isdebug:
                    print("gap closed 1:{0}, {1}".format(working_df[previous_gap_loc][date], TopBotType.value2type(working_df[previous_gap_loc][tb]))) 
                    [print("gap info 3:{0}, {1}".format(working_df[gap_loc][date], TopBotType.value2type(working_df[gap_loc][tb]))) for gap_loc in self.gap_XD]
                i = previous_gap_loc
                
        elif current_direction == TopBotType.bot2top:
            if float_less(min(checking_elems_price), previous_gap_elem[chan_price]):
                previous_gap_loc = self.gap_XD.pop()
                if self.isdebug:
                    print("xd_tb cancelled due to new low found: {0} {1}".format(working_df[previous_gap_loc][date], working_df[previous_gap_loc][real_loc]))
                working_df[previous_gap_loc][xd_tb] = TopBotType.noTopBot.value
                
                self.restore_tb_data(working_df, previous_gap_loc, next_valid_elems[-1])
                current_direction = TopBotType.reverse(current_direction)
                if self.isdebug:
                    print("gap closed 2:{0}, {1}".format(working_df[previous_gap_loc][date],  TopBotType.value2type(working_df[previous_gap_loc][tb])))
                    [print("gap info 3:{0}, {1}".format(working_df[gap_loc][date], TopBotType.value2type(working_df[gap_loc][tb]))) for gap_loc in self.gap_XD]
                i = previous_gap_loc
        return i, current_direction
        #################### pop gap_XD ##########################

    def find_XD(self, initial_i, initial_direction, working_df):
        real_loc = 'real_loc'
        xd_tb = 'xd_tb'
        date = 'date'
        chan_price = 'chan_price'
        tb = 'tb'
        original_tb = 'original_tb'
        if self.isdebug:
            print("Initial direction {0} at location {1} with real_loc {2}".format(initial_direction, initial_i, working_df[initial_i][real_loc]))
        
        current_direction = initial_direction  
        i = initial_i
        while i+5 < working_df.size:
            
            if self.isdebug:
                print("working at {0}, {1}, {2}, {3}, {4}".format(working_df[i][date], 
                                                                  working_df[i][chan_price], 
                                                                  current_direction, 
                                                                  working_df[i][real_loc], 
                                                                  TopBotType.value2type(working_df[i][tb])))
            
            previous_gap = len(self.gap_XD) != 0
            
            if previous_gap:
                # do inclusion find the next two elems we need to do inclusion as we have previous gaps
                next_valid_elems= self.check_inclusion_by_direction(i, working_df, current_direction, count_num=4)
                if len(next_valid_elems) < 4:
                    break
                # make sure we are checking the right elem by direction
                if not self.direction_assert(working_df[next_valid_elems[0]], current_direction):
                    i = next_valid_elems[1]
                    continue
                # check if we have current gap
                current_gap = self.check_current_gap(working_df[next_valid_elems[0]],
                                                     working_df[next_valid_elems[1]],
                                                     working_df[next_valid_elems[2]],
                                                     working_df[next_valid_elems[3]])
                
                # based on current gap info, we find the next elems
                if current_gap: 
                    next_valid_elems= self.check_inclusion_by_direction(next_valid_elems[0], working_df, current_direction, count_num=6)
                else:
                    next_valid_elems= self.check_inclusion_by_direction(next_valid_elems[0], working_df, current_direction, count_num=8)
                
                if len(next_valid_elems) < 6:
                    break
                
                # due to kline gap as xd reasons we do check the current gap again
                current_status, with_current_gap, with_kline_gap_as_xd = self.check_XD_topbot_directed(next_valid_elems, current_direction, working_df)  

                if current_status != TopBotType.noTopBot:
                    if with_current_gap:
                        # save existing gapped Ding/Di
                        self.gap_XD.append(next_valid_elems[2])
                        
                        if self.isdebug:
                            [print("gap info 1:{0}, {1}".format(working_df[gap_loc][date], TopBotType.value2type(working_df[gap_loc][tb]))) for gap_loc in self.gap_XD]
                        
                    else:
                        # fixed Ding/Di, clear the record
                        self.gap_XD = []
                        if self.isdebug:
                            print("gap cleaned!")
                    working_df[next_valid_elems[2]][xd_tb] = current_status.value
                    if self.isdebug:
                        print("xd_tb located {0} {1}".format(working_df[next_valid_elems[2]][date], working_df[next_valid_elems[2]][chan_price]))
                    current_direction = TopBotType.top2bot if current_status == TopBotType.top else TopBotType.bot2top
                    i = next_valid_elems[1] if with_kline_gap_as_xd else next_valid_elems[3]
                    continue
                
                else:
                    i, current_direction = self.pop_gap(working_df, next_valid_elems, current_direction)
                    if i is not None:
                        continue
                
                    i = next_valid_elems[2]
            else:    # no gap case
                # find next 4 elems, we don't do inclusion as there were no gap previously
                next_elems = self.get_next_N_elem(i, working_df, 4)
                if len(next_elems) < 4:
                    break
                
                # check if we have current gap
                current_gap = self.check_current_gap(working_df[next_elems[0]],
                                                     working_df[next_elems[1]],
                                                     working_df[next_elems[2]],
                                                     working_df[next_elems[3]])
                
                # find next 3 elems with the same tb info
                next_single_direction_elems = self.get_next_N_elem(i, working_df, 3, start_tb = TopBotType.top if current_direction == TopBotType.bot2top else TopBotType.bot, single_direction=True)
                
                # make sure we are checking the right elem by direction
                if not self.direction_assert(working_df[next_single_direction_elems[0]], current_direction):
                    i = next_elems[1]
                    continue
                
                # make sure we are targetting the min/max by direction
                possible_xd_tb_idx = self.xd_topbot_candidate(next_single_direction_elems, current_direction, working_df, current_gap)
                if possible_xd_tb_idx is not None:
                    i = possible_xd_tb_idx
                    continue
                
                # find next 6 elems with both direction
                next_valid_elems = self.get_next_N_elem(next_single_direction_elems[0], working_df, 6)
                if len(next_valid_elems) < 6:
                    break  
                
                current_status, with_current_gap, with_kline_gap_as_xd = self.check_XD_topbot_directed(next_valid_elems, current_direction, working_df)
                
                if current_status != TopBotType.noTopBot:
                    previous_xd_tb_idx = self.get_previous_N_elem(next_valid_elems[0], 
                                                                  working_df, 
                                                                  N=0, 
                                                                  end_tb=TopBotType.reverse(current_status), 
                                                                  single_direction=True)
                    if previous_xd_tb_idx:
                        previous_xd_tb_idx = previous_xd_tb_idx[0]
                        if ((working_df[previous_xd_tb_idx][xd_tb] == TopBotType.top.value and                            current_status == TopBotType.bot and                            float_less(working_df[previous_xd_tb_idx][chan_price], working_df[next_valid_elems[2]][chan_price])) or                            (working_df[previous_xd_tb_idx][xd_tb] == TopBotType.bot.value and                            current_status == TopBotType.top and                            float_more(working_df[previous_xd_tb_idx][chan_price], working_df[next_valid_elems[2]][chan_price]))):
                            if self.isdebug:
                                print("current TB not VALID by price with previous TB retrack to {0}".format(working_df[previous_xd_tb_idx][date]))
                            self.restore_tb_data(working_df, previous_xd_tb_idx, next_valid_elems[-1])
                            
                            working_df[previous_xd_tb_idx][xd_tb] = TopBotType.noTopBot.value
                            if self.isdebug:
                                print("{0} {1} cancelled due to higher bot/lower top found".format(working_df[previous_xd_tb_idx][date], 
                                                                                                   TopBotType.value2type(working_df[previous_xd_tb_idx][xd_tb])))
                            current_direction = TopBotType.top2bot if current_status == TopBotType.top else TopBotType.bot2top
                            i = previous_xd_tb_idx
                            continue
                    
                    if with_current_gap:
                        # save existing gapped Ding/Di
                        self.gap_XD.append(next_valid_elems[2])
                        if self.isdebug:
                            [print("gap info 4:{0}, {1}".format(working_df[gap_loc][date], TopBotType.value2type(working_df[gap_loc][tb]))) for gap_loc in self.gap_XD]
                    else:
                        # cleanest case
                        pass
                    
                    working_df[next_valid_elems[2]][xd_tb] = current_status.value
                    if self.isdebug:
                        print("xd_tb located {0} {1}".format(working_df[next_valid_elems[2]][date], working_df[next_valid_elems[2]][chan_price]))
                        
                    current_direction = TopBotType.top2bot if current_status == TopBotType.top else TopBotType.bot2top
                    i = next_valid_elems[1] if with_kline_gap_as_xd else next_valid_elems[3]
                    continue
                else:
                    i = next_valid_elems[2]
                    
        # We need to deal with the remaining BI tb and make an assumption that current XD ends

        # + 3 to make sure we have 3 BI at least in XD
        previous_xd_tb_locs = self.get_previous_N_elem(working_df.shape[0]-1, working_df, N=0, single_direction=False)
        if previous_xd_tb_locs:
            pre_pre_xd_tb_locs = self.get_previous_N_elem(previous_xd_tb_locs[0], working_df, N=0, single_direction=False)
            columns = ['date', chan_price, tb, original_tb]
            previous_xd_tb_loc = previous_xd_tb_locs[0]
            working_xd_tb_loc = previous_xd_tb_loc+3
            
            if working_xd_tb_loc < working_df.shape[0]:
                # restore tb info from loc found from original_tb as we don't need them?
#                 self.restore_tb_data(working_df, working_xd_tb_loc, None)
                
                temp_df = working_df[working_xd_tb_loc:][columns]
                if temp_df.size > 0:
                    temp_df = temp_df[temp_df[tb] != TopBotType.noTopBot.value]
                    gapped_change = False
                    if self.gap_XD: 
                        # with gap we check if there is higher/lower tb for xd_tb
                        if current_direction == TopBotType.top2bot:
                            max_loc = temp_df[chan_price].argmax()
                            max_date = temp_df[max_loc][date]
                            max_price = temp_df[max_loc][chan_price]
                            working_loc = np.where(working_df[date]==max_date)[0][0]
                            if float_more(max_price, working_df[previous_xd_tb_loc][chan_price]):
                                working_df[previous_xd_tb_loc][xd_tb] = TopBotType.noTopBot.value
                                working_df[working_loc][xd_tb] = TopBotType.top.value
                                gapped_change = True
                            if self.isdebug:
                                print("final gapped xd_tb located from {0} for {1}".format(max_date, TopBotType.top))
                        elif current_direction == TopBotType.bot2top:
                            min_loc = temp_df[chan_price].argmin()
                            min_date = temp_df[min_loc][date]
                            min_price = temp_df[min_loc][chan_price]
                            working_loc = np.where(working_df[date]==min_date)[0][0]
                            if float_less(min_price, working_df[previous_xd_tb_loc][chan_price]):
                                working_df[previous_xd_tb_loc][xd_tb] = TopBotType.noTopBot.value
                                working_df[working_loc][xd_tb] = TopBotType.bot.value
                                gapped_change = True
                            if self.isdebug:
                                print("final gapped xd_tb located from {0} for {1}".format(min_date, TopBotType.bot))
                    
                        if gapped_change:
                            working_xd_tb_loc = working_loc+3
                            previous_xd_tb_loc = working_loc
                            temp_df = working_df[working_xd_tb_loc:][columns]
                        
                    # We could make an assumption based on assumption. 
                    if temp_df.size > 0:
                        max_price = temp_df[chan_price].max()
                        min_price = temp_df[chan_price].min()
                        
                        if current_direction == TopBotType.top2bot:
                            # only make guess if previous xd ding is the highest so far
                            if float_more(working_df[previous_xd_tb_loc][chan_price], max_price) or                                (pre_pre_xd_tb_locs and float_more(working_df[pre_pre_xd_tb_locs[0]][chan_price], min_price)):
                                min_loc = temp_df[chan_price].argmin()
                                min_date = temp_df[min_loc][date]
                                working_loc = np.where(working_df[date]==min_date)[0][0]
                                working_df[working_loc][xd_tb] = TopBotType.bot.value
                                if self.isdebug:
                                    print("final xd_tb located from {0} for {1}".format(min_date, TopBotType.bot))
                            elif float_less(working_df[previous_xd_tb_loc][chan_price], max_price):
                                max_loc = temp_df[chan_price].argmax()
                                max_date = temp_df[max_loc][date]
                                working_loc = np.where(working_df[date]==max_date)[0][0]
                                working_df[working_loc][xd_tb] = TopBotType.top.value
                                working_df[previous_xd_tb_loc][xd_tb] = TopBotType.noTopBot.value
                                if self.isdebug:
                                    print("final xd_tb located from {0} for {1}, replacing {2}".format(max_date, 
                                                                                                   TopBotType.top,
                                                                                                   working_df[previous_xd_tb_loc][date]))
                        elif current_direction == TopBotType.bot2top:
                            # only make guess if previous xd di is the lowest so far
                            if float_less(working_df[previous_xd_tb_loc][chan_price], min_price) or                                (pre_pre_xd_tb_locs and float_less(working_df[pre_pre_xd_tb_locs[0]][chan_price], max_price)):
                                max_loc = temp_df[chan_price].argmax()
                                max_date = temp_df[max_loc][date]
                                working_loc = np.where(working_df[date]==max_date)[0][0]
                                working_df[working_loc][xd_tb] = TopBotType.top.value
                                if self.isdebug:
                                    print("final xd_tb located from {0} for {1}".format(max_date, TopBotType.top))
                            elif float_more(working_df[previous_xd_tb_loc][chan_price], min_price):
                                min_loc = temp_df[chan_price].argmin()
                                min_date = temp_df[min_loc][date]
                                working_loc = np.where(working_df[date]==min_date)[0][0]
                                working_df[working_loc][xd_tb] = TopBotType.bot.value
                                working_df[previous_xd_tb_loc][xd_tb] = TopBotType.noTopBot.value
                                if self.isdebug:
                                    print("final xd_tb located from {0} for {1}, replacing {2}".format(min_date, 
                                                                                                   TopBotType.bot,
                                                                                                   working_df[previous_xd_tb_loc][date]))
                        else:
                            print("Invalid direction")
                else:
                    print("empty temp_df, continue")
        
        return working_df
                
    def direction_assert(self, firstElem, direction):
        # make sure we are checking the right elem by direction
        result = True
        if direction == TopBotType.top2bot:
            if firstElem['tb'] != TopBotType.bot.value:
                print("We have invalid elem tb value: {0}".format(firstElem['tb']))
                result = False
        elif direction == TopBotType.bot2top:
            if firstElem['tb'] != TopBotType.top.value:
                print("We have invalid elem tb value: {0}".format(firstElem['tb']))
                result = False
        else:
            result = False
            print("We have invalid direction value!!!!!")
        return result
    


# In[ ]:





# In[ ]:





# In[3]:


# 缠论笔，线段画图
import pandas as pd
from pyecharts import Line, Overlap, Kline
from pyecharts import configure
configure(global_theme='dark')

def draw_chan(stock, stock_df_fenduan, stock_df, kc, end_time): #
    stock_df_original = stock_df[['date', 'open', 'close', 'low', 'high']]
    stock_df_bi = kc.getFenBI_df()[['date','chan_price']]
    stock_df_xd = kc.getFenDuan_df()[['date','chan_price']]
    
    
    overlap = Overlap(width=1500, height=600)
    overlap.use_theme( "dark")
 
    kline = Kline("缠论")
    kline.use_theme( "dark")
    kline.add(stock, 
              stock_df_original['date'].tolist(), 
              stock_df_original[['open', 'close', 'low', 'high']].tolist(), 
              is_datazoom_show=True,
              datazoom_type="both",
              datazoom_range=[80,100], 
              xaxis_interval=10,
              xaxis_rotate=30, 
              background_color='black')
    overlap.add(kline)

    line_1 = Line()
    line_1.use_theme( "dark")
    line_1.add("分笔", 
               stock_df_bi['date'].tolist(), 
               stock_df_bi['chan_price'].tolist(),
               line_color = 'yellow', 
               is_datazoom_show=True,
               datazoom_type="both",
               xaxis_interval=10,
               xaxis_rotate=30)
    overlap.add(line_1)
    
    if stock_df_xd is not None:
        line_2 = Line()
        line_2.use_theme( "dark")
        line_2.add("分段", 
                   stock_df_xd['date'].tolist(), 
                   stock_df_xd['chan_price'].tolist(), 
                   line_color = 'blue',
                   mark_point_symbol="arrow", 
                   is_datazoom_show=True,
                   datazoom_type="both",
                   xaxis_interval=10,
                   xaxis_rotate=30)    
        overlap.add(line_2)
        
    overlap.render("{0}@{1}.html".format(stock, end_time))   
    
from jqdata import * 
stock = '300058.XSHE'
end_time= pd.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
stock_df=get_bars(stock, 
                   count=1000, 
                   end_dt=end_time, 
                   unit='1d',
                   fields= ['date', 'open',  'high', 'low','close'],
                   fq_ref_date = datetime.datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S"),
                   df=False)

kc = KBarChan(stock_df, isdebug=False)
stock_df_fenduan = kc.getFenDuan()

draw_chan(stock, stock_df_fenduan, stock_df, kc, end_time) #


# In[ ]:




