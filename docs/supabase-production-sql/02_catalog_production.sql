BEGIN;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM public.environment_identity WHERE id=1 AND name='production') THEN
   RAISE EXCEPTION 'Маркер production отсутствует';
 END IF;
END $$;
INSERT INTO public.apartments (id, building, rooms, area, floor, total_floors, price, finishing, delivery_year, status) VALUES
('A-101', 'Корпус A', 1, 38.2, 1, 12, 5500000, TRUE, 2027, 'available'),
('A-406', 'Корпус A', 1, 39.5, 4, 12, 5900000, FALSE, 2027, 'available'),
('A-905', 'Корпус A', 1, 41.0, 9, 12, 6400000, FALSE, 2027, 'available'),
('B-203', 'Корпус B', 2, 58.0, 2, 16, 8100000, TRUE, 2027, 'available'),
('B-705', 'Корпус B', 2, 61.0, 7, 16, 8700000, TRUE, 2027, 'available'),
('B-1201', 'Корпус B', 2, 60.0, 12, 16, 8800000, FALSE, 2027, 'available'),
('C-804', 'Корпус C', 2, 64.0, 8, 16, 9400000, TRUE, 2028, 'available'),
('C-1104', 'Корпус C', 3, 74.0, 11, 16, 10200000, TRUE, 2028, 'available'),
('C-301', 'Корпус C', 3, 78.0, 3, 16, 10800000, FALSE, 2028, 'available'),
('C-1403', 'Корпус C', 3, 82.0, 14, 16, 11700000, TRUE, 2028, 'available'),
('A-1203', 'Корпус A', 0, 27.0, 12, 12, 4300000, TRUE, 2027, 'available'),
('B-102', 'Корпус B', 2, 56.0, 1, 16, 7800000, TRUE, 2027, 'available')
ON CONFLICT (id) DO NOTHING;
COMMIT;
