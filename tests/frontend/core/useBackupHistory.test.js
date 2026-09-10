import { buildFileTree, displayFiles, normalizeBackup } from '../../../src/core/useBackupHistory'

describe('core/useBackupHistory helpers', () => {
    describe('buildFileTree', () => {
        it('returns nothing for an empty list', () => {
            expect(buildFileTree([])).toEqual([])
            expect(buildFileTree(null)).toEqual([])
        })

        it('nests paths and keys nodes by their full path', () => {
            expect(buildFileTree(['sys/config.g'])).toEqual([
                { id: 'sys', name: 'sys', children: [{ id: 'sys/config.g', name: 'config.g' }] }
            ])
        })

        it('sorts folders before files, each alphabetically', () => {
            const tree = buildFileTree(['b.g', 'a.g', 'sys/config.g'])
            expect(tree.map(n => n.name)).toEqual(['sys', 'a.g', 'b.g'])
        })

        it('merges files that share a folder', () => {
            const tree = buildFileTree(['sys/config.g', 'sys/homeall.g'])
            expect(tree).toHaveLength(1)
            expect(tree[0].children.map(n => n.name)).toEqual(['config.g', 'homeall.g'])
        })
    })

    describe('displayFiles', () => {
        it('shows every file of a full backup', () => {
            expect(displayFiles({ isFullBackup: true, files: ['a'], changedFiles: ['b'] })).toEqual(['a'])
        })

        it('shows only the changed files of an incremental backup', () => {
            expect(displayFiles({ isFullBackup: false, files: ['a'], changedFiles: ['b'] })).toEqual(['b'])
        })

        it('copes with a backup whose file list was never fetched', () => {
            expect(displayFiles({ hash: 'abc' })).toEqual([])
        })
    })

    describe('normalizeBackup', () => {
        it('initialises every field the history UI will ever set', () => {
            expect(normalizeBackup({ hash: 'abc', message: 'backup' })).toEqual({
                hash: 'abc',
                message: 'backup',
                expanded: false,
                loadingFiles: false,
                loadingDiff: false,
                loadingContent: false,
                changedFiles: null,
                files: null,
                activeNodes: [],
                selectedFile: null,
                fileDiff: null,
                fileContent: null,
                viewMode: 'diff'
            })
        })

        it('keeps fields the entry already carries', () => {
            expect(normalizeBackup({ hash: 'abc', expanded: true }).expanded).toBe(true)
        })
    })
})
