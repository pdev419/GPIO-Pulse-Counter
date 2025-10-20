import argparse, pandas as pd, matplotlib.pyplot as plt

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    # Expect columns: seq,count,rate_hz,status,timestamp
    df['t'] = pd.to_datetime(df['timestamp'])
    fig = plt.figure(figsize=(10,4))
    plt.plot(df['t'], df['rate_hz'])
    plt.title('Rate over time (Hz)')
    plt.xlabel('Time (UTC)')
    plt.ylabel('rate_hz')
    plt.tight_layout()
    plt.savefig(args.out, dpi=150)

if __name__ == '__main__':
    main()  