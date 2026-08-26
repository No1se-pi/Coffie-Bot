import type { BirthdayValue } from "../api/types";
import { Field } from "./ui";

const monthNames = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

export function birthdayDaysInMonth(month: number): number {
  if (month < 1 || month > 12) return 31;
  // A leap-year calendar permits February 29 without collecting or deriving
  // a birth year, which intentionally stays outside the privacy boundary.
  return new Date(Date.UTC(2024, month, 0)).getUTCDate();
}

export function formatBirthday(value: BirthdayValue): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(2024, value.month - 1, value.day)));
}

export function BirthdayFields({
  month,
  day,
  disabled = false,
  onMonthChange,
  onDayChange,
}: {
  month: string;
  day: string;
  disabled?: boolean;
  onMonthChange: (value: string) => void;
  onDayChange: (value: string) => void;
}) {
  return (
    <div className="form-grid">
      <Field label="Месяц рождения">
        <select
          required
          value={month}
          disabled={disabled}
          onChange={(event) => onMonthChange(event.target.value)}
        >
          <option value="">Выберите месяц</option>
          {monthNames.map((name, index) => (
            <option key={name} value={index + 1}>
              {name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="День рождения">
        <select
          required
          value={day}
          disabled={disabled || !month}
          onChange={(event) => onDayChange(event.target.value)}
        >
          <option value="">Выберите день</option>
          {Array.from(
            { length: birthdayDaysInMonth(Number(month)) },
            (_, index) => index + 1,
          ).map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </Field>
    </div>
  );
}
