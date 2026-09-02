import { useEffect } from "react";
import {
  AttributionControl,
  Circle,
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";

export interface GeoPoint {
  latitude: number;
  longitude: number;
}

function MapClick({ onChange }: { onChange?: (value: GeoPoint) => void }) {
  useMapEvents({
    click(event) {
      onChange?.({
        latitude: Number(event.latlng.lat.toFixed(6)),
        longitude: Number(event.latlng.lng.toFixed(6)),
      });
    },
  });
  return null;
}

function Recenter({ point }: { point: GeoPoint }) {
  const map = useMap();
  useEffect(() => {
    map.setView([point.latitude, point.longitude], map.getZoom());
  }, [map, point.latitude, point.longitude]);
  return null;
}

export function DeliveryMap({
  center,
  marker,
  radiusMeters,
  onMarkerChange,
  markerLabel = "Выбранный адрес",
}: {
  center?: GeoPoint | null;
  marker?: GeoPoint | null;
  radiusMeters?: number | null;
  onMarkerChange?: (value: GeoPoint) => void;
  markerLabel?: string;
}) {
  const focus = marker ??
    center ?? { latitude: 55.751244, longitude: 37.618423 };
  return (
    <div className="delivery-map">
      <MapContainer
        center={[focus.latitude, focus.longitude]}
        zoom={13}
        scrollWheelZoom
        attributionControl={false}
      >
        {/* Keep the required map-data credit while hiding Leaflet's optional branded prefix. */}
        <AttributionControl prefix={false} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Recenter point={focus} />
        <MapClick onChange={onMarkerChange} />
        {center && (
          <>
            <CircleMarker
              center={[center.latitude, center.longitude]}
              radius={9}
              pathOptions={{ color: "#6f3f22", fillOpacity: 1 }}
            >
              <Popup>Точка заведения</Popup>
            </CircleMarker>
            {radiusMeters && (
              <Circle
                center={[center.latitude, center.longitude]}
                radius={radiusMeters}
                pathOptions={{ color: "#d48632", fillOpacity: 0.12 }}
              />
            )}
          </>
        )}
        {marker && (
          <CircleMarker
            center={[marker.latitude, marker.longitude]}
            radius={8}
            pathOptions={{ color: "#1b6b50", fillOpacity: 1 }}
          >
            <Popup>{markerLabel}</Popup>
          </CircleMarker>
        )}
      </MapContainer>
      {onMarkerChange && (
        <small className="muted">
          Нажмите на карту, чтобы поставить маркер.
        </small>
      )}
    </div>
  );
}
