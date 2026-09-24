"""The regridded tables cannot hold the same row twice.

`regrid_members.py` writes with `COPY`, which cannot express `ON CONFLICT`, so
re-running a regrid over hours already present used to append a second copy of
every row. Nothing complained, and every score was then computed over
duplicated members — a spread that looks plausible and is wrong.

Two things stop it now and both are tested here, because either alone is
insufficient. `clear_slice` removes exactly what a pass is about to write,
which is what makes a re-run correct; the unique indexes are the backstop that
turns a *missed* clear into a loud failure instead of silent doubling.

Runs against the fixture database, which builds its schema from the same DDL
the real one uses — so an index deleted from `INDEXES` fails here.
"""
import pytest


@pytest.fixture(scope='module')
def conn(fixture_db):
    """A connection onto the shared fixture database.

    Depends on conftest's session-scoped `fixture_db` rather than calling
    `build()` here. Building again drops the database, which fails while
    another module still holds a session on it — and passed in isolation,
    which is how it got written that way.
    """
    import psycopg2
    c = psycopg2.connect(**fixture_db.db_config())
    yield c
    c.close()


MEMBER = 'regridded_forecast_member'
ENS    = 'regridded_forecast_ens'


class TestTheNaturalKeyIsEnforced:
    @pytest.mark.parametrize('table,index', [
        (MEMBER, 'uq_rfm_natural_key'),
        (ENS,    'uq_rfe_natural_key'),
    ])
    def test_the_unique_index_exists(self, conn, table, index):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT idx.indisunique
                FROM pg_index idx
                JOIN pg_class i ON i.oid = idx.indexrelid
                WHERE i.relname = %s
            """, (index,))
            row = cur.fetchone()
        assert row is not None, f'{index} is missing from {table}'
        assert row[0] is True, f'{index} exists but is not unique'

    def test_the_member_key_includes_ensemble_member(self, conn):
        """`idx_rfm_run` looks similar and is not a substitute: it is not
        unique, and it omits the member, which is part of what identifies a
        member row. Two members of the same cell and hour are not duplicates.
        """
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.attname
                FROM pg_index idx
                JOIN pg_class i ON i.oid = idx.indexrelid
                JOIN pg_attribute a ON a.attrelid = idx.indrelid
                                   AND a.attnum = ANY(idx.indkey)
                WHERE i.relname = 'uq_rfm_natural_key'
            """)
            columns = {r[0] for r in cur.fetchall()}
        assert 'ensemble_member' in columns
        assert {'model_name', 'variable_name', 'init_time',
                'forecast_hour', 'latitude', 'longitude'} <= columns

    def test_inserting_the_same_member_row_twice_is_refused(self, conn):
        """The backstop. If `clear_slice` is ever skipped or a future writer
        forgets it, this is what turns silent doubling into an error."""
        import psycopg2
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT model_name, variable_name, init_time, forecast_hour,
                       ensemble_member, latitude, longitude, value
                FROM {MEMBER} LIMIT 1
            """)
            row = cur.fetchone()
        assert row is not None, 'fixture seeded no member rows'

        with pytest.raises(psycopg2.errors.UniqueViolation):
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {MEMBER}
                        (model_name, variable_name, init_time, forecast_hour,
                         ensemble_member, latitude, longitude, value)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, row)
        conn.rollback()

    def test_two_members_of_the_same_cell_are_not_duplicates(self, conn):
        """Guards the guard: a key that omitted `ensemble_member` would make
        the ensemble itself a constraint violation, which would be a far
        louder bug than the one being fixed."""
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT count(DISTINCT ensemble_member)
                FROM {MEMBER}
                WHERE forecast_hour = (SELECT MIN(forecast_hour) FROM {MEMBER})
                GROUP BY model_name, variable_name, init_time,
                         forecast_hour, latitude, longitude
                ORDER BY 1 DESC LIMIT 1
            """)
            most = cur.fetchone()[0]
        assert most > 1, 'the fixture should hold several members per cell'


class TestClearSliceScopesItself:
    def test_it_removes_only_the_hour_it_is_given(self, conn):
        """Re-running one hour must not disturb the rest of the run — which is
        what makes a partial re-run useful rather than destructive."""
        import regrid_members
        # Model, variable and hours must come from the *same* series. Picking
        # the hour globally and the model separately gave a combination the
        # fixture does not hold, and the delete matched nothing — a test that
        # passes vacuously in the other direction.
        with conn.cursor() as cur:
            cur.execute(f"""SELECT model_name, variable_name, init_time,
                                   array_agg(DISTINCT forecast_hour ORDER BY forecast_hour)
                            FROM {MEMBER}
                            GROUP BY 1, 2, 3
                            HAVING count(DISTINCT forecast_hour) > 1
                            LIMIT 1""")
            found = cur.fetchone()
        assert found, 'need a series with at least two hours to prove scoping'
        model, variable, init_time, hours = found

        target, other = hours[0], hours[1]

        def count(hour):
            with conn.cursor() as cur:
                cur.execute(f"""SELECT count(*) FROM {MEMBER}
                                WHERE model_name=%s AND variable_name=%s
                                  AND init_time=%s AND forecast_hour=%s""",
                            (model, variable, init_time, hour))
                return cur.fetchone()[0]

        before_other = count(other)
        removed = regrid_members.clear_slice(conn, MEMBER, model, variable,
                                             init_time, target)
        assert removed > 0
        assert count(target) == 0
        assert count(other) == before_other      # untouched
        conn.rollback()
