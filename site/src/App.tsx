import { Route, Routes } from 'react-router'
import Layout from './components/Layout'
import About from './pages/About'
import Film from './pages/Film'
import Films from './pages/Films'
import Home from './pages/Home'
import Leaderboard from './pages/Leaderboard'
import NotFound from './pages/NotFound'
import People from './pages/People'
import Person from './pages/Person'
import Search from './pages/Search'
import Weekend from './pages/Weekend'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="films" element={<Films />} />
        <Route path="film/:titleId" element={<Film />} />
        <Route path="leaderboard" element={<Leaderboard />} />
        <Route path="people" element={<People />} />
        <Route path="person/:personId" element={<Person />} />
        <Route path="weekend" element={<Weekend />} />
        <Route path="search" element={<Search />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
