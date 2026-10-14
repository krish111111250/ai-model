/**
 * A placeholder shaped like the thing that is loading.
 *
 * Worth more than a spinner because it says what is coming: the page does not
 * jump when the data lands, and a table does not flash "0 keys" on its way to
 * showing three.
 */
export const Skeleton = ({ className = '' }) => (
  <div className={`shimmer rounded bg-secondary ${className}`} />
);

/**
 * Rows that mirror a table's columns, so the skeleton collapses at the same
 * breakpoints the real rows do.
 */
export const SkeletonRows = ({ rows = 3, columns }) => (
  <>
    {Array.from({ length: rows }).map((_, row) => (
      <tr key={row} className="border-b border-border last:border-0">
        {columns.map((column, index) => (
          <td key={index} className={`px-5 py-4 ${column.className || ''}`}>
            <Skeleton className={`h-3.5 ${column.width}`} />

            {column.second && (
              <Skeleton className={`mt-2 h-2.5 ${column.second}`} />
            )}
          </td>
        ))}
      </tr>
    ))}
  </>
);

export default Skeleton;
