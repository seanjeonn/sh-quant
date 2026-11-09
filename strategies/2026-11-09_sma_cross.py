import pandas as pd

META = {
    "name": "SMA 50/200 골든크로스",
    "hypothesis": "장기 추세(50일선 > 200일선) 구간에만 보유하면 하락장 MDD를 줄이면서 수익 대부분을 얻는다.",
    "tags": ["trend", "single"],
    "parents": [],
    "source": "seed",
}


def signal(df: pd.DataFrame) -> pd.Series:
    c = df["Close"]
    return (c.rolling(50).mean() > c.rolling(200).mean()).astype(float)
