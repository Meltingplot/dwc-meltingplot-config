import {
    computeSelection,
    diffStatusColor,
    fileChecked,
    fileIsPartial,
    fileStatusColor,
    fileStatusIcon,
    hasHunkDetail,
    normalizeFile,
    normalizeHunk,
    parseHunkHeader,
    selectedHunkCount,
    sideBySideLines,
    skippedLinesBetween
} from '../../../src/core/diff'

const detailHunk = (index, header, lines) => ({ index, header, lines })

describe('core/diff', () => {
    describe('status maps', () => {
        it('maps known file statuses', () => {
            expect(fileStatusColor('modified')).toBe('warning')
            expect(fileStatusColor('missing')).toBe('info')
            expect(fileStatusColor('extra')).toBe('grey')
            expect(fileStatusIcon('missing')).toBe('mdi-file-plus')
        })

        it('falls back to "modified" for unknown file statuses', () => {
            expect(fileStatusColor('nonsense')).toBe('warning')
            expect(fileStatusIcon('nonsense')).toBe('mdi-file-document-edit')
        })

        it('maps backup diff statuses with a grey fallback', () => {
            expect(diffStatusColor('added')).toBe('success')
            expect(diffStatusColor('deleted')).toBe('error')
            expect(diffStatusColor('nonsense')).toBe('grey')
        })
    })

    describe('parseHunkHeader', () => {
        it('parses explicit counts', () => {
            expect(parseHunkHeader('@@ -12,4 +14,6 @@')).toEqual({
                oldStart: 12, oldCount: 4, newStart: 14, newCount: 6
            })
        })

        it('defaults an omitted count to 1', () => {
            expect(parseHunkHeader('@@ -3 +7 @@')).toEqual({
                oldStart: 3, oldCount: 1, newStart: 7, newCount: 1
            })
        })

        it('returns null for empty or malformed headers', () => {
            expect(parseHunkHeader('')).toBeNull()
            expect(parseHunkHeader(undefined)).toBeNull()
            expect(parseHunkHeader('not a hunk header')).toBeNull()
        })
    })

    describe('skippedLinesBetween', () => {
        it('counts the lines before the first hunk', () => {
            const file = { hunks: [detailHunk(0, '@@ -10,2 +10,2 @@', [])] }
            expect(skippedLinesBetween(file, 0)).toBe(9)
        })

        it('is zero when the first hunk starts at line 1', () => {
            const file = { hunks: [detailHunk(0, '@@ -1,2 +1,2 @@', [])] }
            expect(skippedLinesBetween(file, 0)).toBe(0)
        })

        it('counts the gap between two hunks', () => {
            const file = {
                hunks: [
                    detailHunk(0, '@@ -1,3 +1,3 @@', []),
                    detailHunk(1, '@@ -20,2 +20,2 @@', [])
                ]
            }
            expect(skippedLinesBetween(file, 1)).toBe(16)
        })

        it('is zero when a header cannot be parsed', () => {
            const file = { hunks: [detailHunk(0, 'broken', [])] }
            expect(skippedLinesBetween(file, 0)).toBe(0)
        })
    })

    describe('sideBySideLines', () => {
        it('returns nothing for a summary hunk without lines', () => {
            expect(sideBySideLines({ index: 0, header: '@@ -1,1 +1,1 @@' })).toEqual([])
        })

        it('pairs a remove with an add and numbers both sides', () => {
            const rows = sideBySideLines(detailHunk(0, '@@ -5,1 +7,1 @@', ['-old', '+new']))
            expect(rows).toEqual([{
                leftLine: 5, left: 'old', leftClass: 'diff-remove',
                rightLine: 7, right: 'new', rightClass: 'diff-add'
            }])
        })

        it('renders context lines on both sides', () => {
            const rows = sideBySideLines(detailHunk(0, '@@ -1,1 +1,1 @@', [' ctx']))
            expect(rows[0].left).toBe('ctx')
            expect(rows[0].right).toBe('ctx')
            expect(rows[0].leftClass).toBe('diff-context')
        })

        it('leaves an empty cell for an unbalanced run', () => {
            const rows = sideBySideLines(detailHunk(0, '@@ -1,2 +1,1 @@', ['-a', '-b', '+c']))
            expect(rows).toHaveLength(2)
            expect(rows[1].right).toBeNull()
            expect(rows[1].rightClass).toBe('diff-empty')
            expect(rows[1].rightLine).toBeNull()
        })

        it('keeps the line numbers running across hunk sections', () => {
            const rows = sideBySideLines(
                detailHunk(0, '@@ -1,3 +1,3 @@', [' a', '-b', '+B', ' c'])
            )
            expect(rows.map(r => r.leftLine)).toEqual([1, 2, 3])
            expect(rows.map(r => r.rightLine)).toEqual([1, 2, 3])
        })

        it('treats a line without a marker as context', () => {
            const rows = sideBySideLines(detailHunk(0, '@@ -1,1 +1,1 @@', ['bare']))
            expect(rows[0].left).toBe('bare')
        })
    })

    describe('normalizers', () => {
        it('gives a hunk a selected flag', () => {
            expect(normalizeHunk({ index: 0 })).toEqual({ index: 0, selected: true })
            expect(normalizeHunk({ index: 0 }, false).selected).toBe(false)
        })

        it('keeps a selected flag the hunk already carries', () => {
            expect(normalizeHunk({ index: 0, selected: false }, true).selected).toBe(false)
        })

        it('initialises every field a file entry will ever carry', () => {
            expect(normalizeFile({ file: 'sys/config.g', status: 'modified' })).toEqual({
                file: 'sys/config.g',
                status: 'modified',
                selected: true,
                loadingDetail: false,
                hunks: null
            })
        })

        it('carries the file selection into its hunks', () => {
            const normalized = normalizeFile({
                file: 'sys/config.g', status: 'modified', selected: false,
                hunks: [{ index: 0 }, { index: 1 }]
            })
            expect(normalized.hunks.every(h => h.selected === false)).toBe(true)
        })

        it('is idempotent', () => {
            const once = normalizeFile({ file: 'a', status: 'modified', hunks: [{ index: 0 }] })
            expect(normalizeFile(once)).toEqual(once)
        })
    })

    describe('hunk detail and selection predicates', () => {
        const withDetail = (selected) => ({
            file: 'sys/config.g',
            status: 'modified',
            selected: true,
            hunks: [
                { index: 0, header: '@@ -1,1 +1,1 @@', lines: ['-a', '+b'], selected: selected[0] },
                { index: 1, header: '@@ -5,1 +5,1 @@', lines: ['-c', '+d'], selected: selected[1] }
            ]
        })

        it('only sees detail once hunks carry lines', () => {
            expect(hasHunkDetail({ hunks: [{ index: 0, header: '@@' }] })).toBe(false)
            expect(hasHunkDetail({ hunks: null })).toBe(false)
            expect(hasHunkDetail({ hunks: [] })).toBe(false)
            expect(hasHunkDetail(withDetail([true, true]))).toBe(true)
        })

        it('counts selected hunks', () => {
            expect(selectedHunkCount(withDetail([true, false]))).toBe(1)
            expect(selectedHunkCount({ hunks: null })).toBe(0)
        })

        it('reads an explicitly excluded file as unchecked', () => {
            expect(fileChecked({ status: 'modified', selected: false })).toBe(false)
        })

        it('reads a file with no hunk detail as checked', () => {
            expect(fileChecked({ status: 'modified', selected: true, hunks: null })).toBe(true)
        })

        it('reads a file with every hunk deselected as unchecked', () => {
            expect(fileChecked(withDetail([false, false]))).toBe(false)
        })

        it('reads a partly selected file as checked and indeterminate', () => {
            const file = withDetail([true, false])
            expect(fileChecked(file)).toBe(true)
            expect(fileIsPartial(file)).toBe(true)
        })

        it('is not partial when all or no hunks are selected', () => {
            expect(fileIsPartial(withDetail([true, true]))).toBe(false)
            expect(fileIsPartial(withDetail([false, false]))).toBe(false)
        })

        it('is not partial for excluded files or files without detail', () => {
            expect(fileIsPartial({ status: 'modified', selected: false })).toBe(false)
            expect(fileIsPartial({ status: 'missing', selected: true })).toBe(false)
        })
    })

    describe('computeSelection', () => {
        it('sends whole-file entries when nothing is deselected', () => {
            expect(computeSelection([
                { file: 'sys/config.g', status: 'modified', selected: true },
                { file: 'sys/homeall.g', status: 'missing', selected: true }
            ])).toEqual({
                files: [{ file: 'sys/config.g' }, { file: 'sys/homeall.g' }],
                excludedFiles: 0,
                partialFiles: 0
            })
        })

        it('drops "extra" files without counting them as excluded', () => {
            expect(computeSelection([
                { file: 'sys/leftover.g', status: 'extra', selected: true }
            ])).toEqual({ files: [], excludedFiles: 0, partialFiles: 0 })
        })

        it('counts a deselected file as excluded', () => {
            const result = computeSelection([
                { file: 'sys/config.g', status: 'modified', selected: false },
                { file: 'sys/homeall.g', status: 'modified', selected: true }
            ])
            expect(result.excludedFiles).toBe(1)
            expect(result.files).toEqual([{ file: 'sys/homeall.g' }])
        })

        it('sends only the selected hunk indices of a partial file', () => {
            const result = computeSelection([{
                file: 'sys/config.g',
                status: 'modified',
                selected: true,
                hunks: [
                    { index: 0, lines: ['-a', '+b'], selected: true },
                    { index: 1, lines: ['-c', '+d'], selected: false },
                    { index: 2, lines: ['-e', '+f'], selected: true }
                ]
            }])
            expect(result).toEqual({
                files: [{ file: 'sys/config.g', hunks: [0, 2] }],
                excludedFiles: 0,
                partialFiles: 1
            })
        })

        it('sends a whole-file entry when every hunk stays selected', () => {
            const result = computeSelection([{
                file: 'sys/config.g',
                status: 'modified',
                selected: true,
                hunks: [{ index: 0, lines: ['-a', '+b'], selected: true }]
            }])
            expect(result.files).toEqual([{ file: 'sys/config.g' }])
            expect(result.partialFiles).toBe(0)
        })

        it('treats a file with every hunk deselected as excluded, not partial', () => {
            const result = computeSelection([{
                file: 'sys/config.g',
                status: 'modified',
                selected: true,
                hunks: [{ index: 0, lines: ['-a', '+b'], selected: false }]
            }])
            expect(result).toEqual({ files: [], excludedFiles: 1, partialFiles: 0 })
        })
    })
})
