import { useCallback, useEffect, useMemo, useState } from "react";
import type { Venue } from "../api/types";

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
    <section className="venue-picker" aria-labelledby="venue-picker-title">
      <label className="sr-only">
        Заведение
        <select
          value={selectedVenueId ?? ""}
          onChange={(event) => onSelect(event.target.value)}
        >
          {venues.map((venue) => (
            <option key={venue.id} value={venue.id}>
              {venue.name}
            </option>
          ))}
        </select>
      </label>
      <div className="section-heading">
        <div>
          <small className="eyebrow">Сейчас выбрано</small>
          <h2 id="venue-picker-title">{selectedVenue?.name ?? "Заведение"}</h2>
        </div>
      </div>
      <div
        className="venue-picker__rail"
        role="list"
        aria-label="Выбор заведения"
      >
        {venues.map((venue, index) => (
          <button
            type="button"
            role="listitem"
            key={venue.id}
            className={`venue-card ${venue.id === selectedVenueId ? "is-active" : ""}`}
            onClick={() => onSelect(venue.id)}
            aria-pressed={venue.id === selectedVenueId}
          >
            <span
              className={`venue-card__visual venue-card__visual--${index % 4}`}
            >
              {venue.logo_url ? (
                <img src={venue.logo_url} alt="" />
              ) : (
                <b>{venue.name.trim().charAt(0).toLocaleUpperCase()}</b>
              )}
            </span>
            <span className="venue-card__copy">
              <strong>{venue.name}</strong>
              <small>
                {venue.description || "Меню и предложения заведения"}
              </small>
            </span>
            <span aria-hidden="true">›</span>
          </button>
        ))}
      </div>
    </section>
  );
}
