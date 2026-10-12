import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Join class names, letting a later class win over an earlier one.
 *
 * Plain template strings cannot do that: "p-2" and "p-4" would both land in
 * the output and the winner would depend on stylesheet order. Every shadcn
 * component imports this.
 */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
