export const when = (value: string | null | undefined) => (value ? new Date(value).toLocaleString() : "never");
export const day = (value: string | null | undefined) => (value ? new Date(value).toLocaleDateString() : "–");
export const num = (value: number) => value.toLocaleString();
export const usd = (value: number) => (value === 0 ? "$0" : value < 0.01 ? "<$0.01" : `$${value.toFixed(2)}`);
