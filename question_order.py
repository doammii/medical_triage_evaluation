import pandas as pd
import numpy as np

# 1. 엑셀 파일 불러오기
# openpyxl 라이브러리가 설치되어 있어야 합니다 (pip install openpyxl)
input_file = 'evaluation_data.xlsx'
df = pd.read_excel(input_file)

# 2. 데이터 개수 확인 및 랜덤 '문제번호' 생성
# 1부터 전체 행 개수까지의 숫자를 중복 없이 무작위로 섞습니다.
num_rows = len(df)
random_numbers = np.random.permutation(np.arange(1, num_rows + 1))

# 3. 'index' 컬럼 위치 확인 후 오른쪽에 '문제번호' 추가
if 'index' in df.columns:
    idx_pos = df.columns.get_loc('index')
    df.insert(idx_pos + 1, '문제번호', random_numbers)
else:
    df.insert(0, '문제번호', random_numbers)

# 4. 수정된 내용을 다시 엑셀 파일로 저장
output_file = 'evaluation_data.xlsx'
df.to_excel(output_file, index=False)

print(f"작업이 완료되었습니다!")
print(f"출력 파일: {output_file} (문제번호 컬럼 추가됨)")