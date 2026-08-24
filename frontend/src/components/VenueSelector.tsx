import { useCallback, useEffect, useMemo, useState } from "react";
import type { Venue } from "../api/types";
import { Field, Panel } from "./ui";

export const SELECTED_VENUE_STORAGE_KEY = "coffie.selected-venue-id";

function readStoredVenueId(): string | null {
  try {
    return window.localStorage.getItem(SELECTED_VENUE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistVenueId(venueId: string | null): void {
  try {
    if (venueId) {
      window.localStorage.setItem(SELECTED_VENUE_STORAGE_KEY, venueId);
    } else {
      window.localStorage.removeItem(SELECTED_VENUE_STORAGE_KEY);
    }
  } catch {
    // The selector still works for the current render when storage is unavailable.
  }
}

export function useVenueSelection(venues: Venue[] | null) {
  const [selectedVenueId, setSelectedVenueId] = useState(readStoredVenueId);

  useEffect(() => {
    if (venues === null) return;

    // Storage is only a preference: reconcile it with the authenticated public
    // list so an archived or removed venue can never remain selected.
    const reconciledVenueId = venues.some(
      (venue) => venue.id === selectedVenueId,
    )
      ? selectedVenueId
      : (venues[0]?.id ?? null);

    if (reconciledVenueId !== selectedVenueId) {
      setSelectedVenueId(reconciledVenueId);
    }
    persistVenueId(reconciledVenueId);
  }, [selectedVenueId, venues]);

  const selectVenue = useCallback(
    (venueId: string) => {
      if (!venues?.some((venue) => venue.id === venueId)) return;
      setSelectedVenueId(venueId);
      persistVenueId(venueId);
    },
    [venues],
  );

  return { selectedVenueId, selectVenue };
}

export function VenueSelector({
  venues,
  selectedVenueId,
  onSelect,
}: {
  venues: Venue[];
  selectedVenueId: string | null;
  onSelect: (venueId: string) => void;
}) {
  const selectedVenue = useMemo(
    () => venues.find((venue) => venue.id === selectedVenueId) ?? null,
    [selectedVenueId, venues],
  );

  return (
    <Panel>
      <Field label="Заведение">
        <select
          value={selectedVenueId ?? ""}
          onChange={(event) => onSelect(event.target.value)}
        >
          {venues.map((venue) => (
            <option value={venue.id} key={venue.id}>
              {venue.name}
            </option>
          ))}
        </select>
      </Field>
      {selectedVenue?.description && (
        <p className="muted">{selectedVenue.description}</p>
      )}
    </Panel>
  );
}
