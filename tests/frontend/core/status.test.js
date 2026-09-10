import { SYNC_STATUS, syncStatusInfo } from '../../../src/core/status'

describe('core/status', () => {
    it('maps every status the daemon reports', () => {
        expect(Object.keys(SYNC_STATUS)).toEqual([
            'not_configured', 'up_to_date', 'updates_available', 'sync_error', 'error'
        ])
    })

    it('returns colour, icon and label', () => {
        expect(syncStatusInfo('up_to_date')).toEqual({
            color: 'success', icon: 'mdi-check-circle', label: 'Up to Date'
        })
    })

    it('falls back to "not configured" for unknown and missing statuses', () => {
        expect(syncStatusInfo('nonsense').label).toBe('Not Configured')
        expect(syncStatusInfo(undefined).label).toBe('Not Configured')
    })
})
